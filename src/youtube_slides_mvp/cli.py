from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .dedupe import DedupeConfig, _dark_cover, _directional_change, _load_gray, dedupe_frames
from .extract import build_frame_rows, find_downloaded_video, write_frame_manifest
from .health import run_healthcheck
from .manifest import build_task_paths, ensure_task_dirs, make_task_id, write_manifest
from .models import TaskManifest, TaskStatus
from .ocr_refill import detect_suspect_windows, run_ocr_signals, write_ocr_report
from .preprocess import load_mask_profile, preprocess_frames, write_mask_profile
from .quality import compute_quality_metrics, evaluate_gate, write_quality_markdown, write_quality_report
from .refill import extract_refill_window_frames, refill_rows_for_window, split_window_ranges
from .scene import detect_scene_driven_windows
from .render import render_pdf_a, render_pdf_b_with_index, render_pdf_raw, write_slides_json


def _download_video(url: str, video_dir: Path, retries: int) -> tuple[bool, str]:
    formats = [
        "(bestvideo[height<=1080]+bestaudio)/best[height<=1080]/best",
        "best[ext=mp4]/best",
    ]
    last_error = "download failed"

    for fmt in formats:
        for attempt in range(1, retries + 1):
            cmd = [
                "yt-dlp",
                "-f",
                fmt,
                "-o",
                str(video_dir / "video.%(ext)s"),
                url,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return True, f"download completed with format {fmt}"
            last_error = (proc.stderr or proc.stdout or "download failed").strip().splitlines()[-1]
            print(f"download attempt {attempt}/{retries} failed for format {fmt}: {last_error}")

    return False, last_error


def _extract_frames(video_path: Path, frames_dir: Path, fps: float) -> tuple[bool, str]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "2",
        str(frames_dir / "frame_%06d.jpg"),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return True, "frame extraction completed"
    err = (proc.stderr or proc.stdout or "frame extraction failed").strip().splitlines()[-1]
    return False, err


def _load_frame_rows(frame_manifest_path: Path) -> list[dict[str, int | float | str]]:
    import json

    data = json.loads(frame_manifest_path.read_text(encoding="utf-8"))
    return list(data.get("frames", []))


def _rows_for_selected(selected: list[Path], frame_rows: list[dict[str, int | float | str]]) -> list[dict[str, int | float | str]]:
    by_name = {str(r["frame_name"]): r for r in frame_rows}
    rows: list[dict[str, int | float | str]] = []
    for page, frame in enumerate(selected, start=1):
        row = dict(by_name.get(frame.name, {}))
        row["frame_name"] = frame.name
        row["page"] = page
        row.setdefault("timestamp_sec", 0.0)
        row.setdefault("timestamp_ms", 0)
        rows.append(row)
    return rows


def _merge_with_refill_and_rededupe(
    selected_rows: list[dict[str, int | float | str]],
    selected_orig: list[Path],
    selected_norm_dir: Path,
    refill_rows: list[dict[str, int | float | str]],
    refill_raw_paths: list[Path],
    refill_norm_dir: Path,
    work_dir: Path,
    cfg: DedupeConfig,
) -> tuple[list[Path], list[dict[str, int | float | str]], dict[str, int]]:
    if not refill_rows:
        return selected_orig, selected_rows, {"merged_input": len(selected_orig), "merged_output": len(selected_orig)}

    by_raw_name = {p.name: p for p in selected_orig}
    by_norm_name = {p.name: p for p in selected_norm_dir.glob("frame_*.jpg")}
    refill_raw_name = {p.name: p for p in refill_raw_paths}
    refill_norm_name = {p.name: p for p in refill_norm_dir.glob("*.jpg")}

    combined: list[dict[str, object]] = []
    for row in selected_rows:
        name = str(row["frame_name"])
        raw = by_raw_name.get(name)
        norm = by_norm_name.get(name)
        if raw is None or norm is None:
            continue
        combined.append({"timestamp_sec": float(row["timestamp_sec"]), "row": dict(row), "raw": raw, "norm": norm})

    for row in refill_rows:
        name = str(row["frame_name"])
        raw = refill_raw_name.get(name)
        norm = refill_norm_name.get(name)
        if raw is None or norm is None:
            continue
        combined.append({"timestamp_sec": float(row["timestamp_sec"]), "row": dict(row), "raw": raw, "norm": norm})

    if not combined:
        return selected_orig, selected_rows, {"merged_input": len(selected_orig), "merged_output": len(selected_orig)}

    combined.sort(key=lambda x: float(x["timestamp_sec"]))
    seq_dir = work_dir / "merged_norm_seq"
    seq_dir.mkdir(parents=True, exist_ok=True)

    seq_map: dict[str, dict[str, object]] = {}
    seq_paths: list[Path] = []
    for idx, item in enumerate(combined, start=1):
        seq_name = f"frame_{idx:06d}.jpg"
        dest = seq_dir / seq_name
        shutil.copy(item["norm"], dest)
        seq_paths.append(dest)
        seq_map[seq_name] = item

    selected_seq, _ = dedupe_frames(seq_paths, cfg)

    out_raw: list[Path] = []
    out_rows: list[dict[str, int | float | str]] = []
    for page, seq in enumerate(selected_seq, start=1):
        item = seq_map.get(seq.name)
        if item is None:
            continue
        raw = item["raw"]
        row = dict(item["row"])
        row["page"] = page
        out_raw.append(raw)
        out_rows.append(row)

    return out_raw, out_rows, {"merged_input": len(combined), "merged_output": len(out_raw)}


def _merge_windows(
    scene_windows: list[dict[str, int | float | str]],
    ocr_windows: list[dict[str, int | float | str]],
) -> list[dict[str, int | float | str]]:
    merged = list(scene_windows)
    for win in ocr_windows:
        s2 = float(win.get("start_ts", 0.0))
        e2 = float(win.get("end_ts", s2))
        overlaps = False
        for existing in merged:
            s1 = float(existing.get("start_ts", 0.0))
            e1 = float(existing.get("end_ts", s1))
            if not (e2 < s1 or e1 < s2):
                overlaps = True
                break
        if not overlaps:
            merged.append(win)
    merged.sort(key=lambda w: float(w.get("start_ts", 0.0)))
    return merged


def _is_blank_transition_frame(path: Path) -> bool:
    img = Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)
    mean = float(arr.mean())
    std = float(arr.std())
    gy = np.abs(np.diff(arr.astype(np.float32), axis=0))
    gx = np.abs(np.diff(arr.astype(np.float32), axis=1))
    edge_var = float(np.var(np.concatenate([gx.ravel(), gy.ravel()])))
    return mean < 28.0 and std < 8.0 and edge_var < 5.0


def _drop_blank_transition_pages(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    if not selected_orig or len(selected_orig) != len(selected_rows):
        return selected_orig, selected_rows, 0

    blank_flags = [_is_blank_transition_frame(p) for p in selected_orig]
    keep = [True] * len(selected_orig)
    dropped = 0

    for i, is_blank in enumerate(blank_flags):
        if not is_blank:
            continue
        prev_nonblank = i > 0 and not blank_flags[i - 1]
        next_nonblank = i + 1 < len(blank_flags) and not blank_flags[i + 1]
        if prev_nonblank or next_nonblank:
            keep[i] = False
            dropped += 1

    if dropped == 0:
        return selected_orig, selected_rows, 0

    out_orig: list[Path] = []
    out_rows: list[dict[str, int | float | str]] = []
    for p, row, k in zip(selected_orig, selected_rows, keep):
        if not k:
            continue
        out_orig.append(p)
        out_rows.append(dict(row))

    paired = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0.0)))
    out_orig = [p for p, _ in paired]
    out_rows = [dict(r) for _, r in paired]
    for page, row in enumerate(out_rows, start=1):
        row["page"] = page

    return out_orig, out_rows, dropped


def _rescue_gap_pages(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    frame_rows: list[dict[str, int | float | str]],
    frames_raw_dir: Path,
    min_gap_sec: float = 20.0,
    novelty_th: float = 0.075,
    max_rounds: int = 3,
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    if len(selected_orig) < 2 or len(selected_rows) != len(selected_orig):
        return selected_orig, selected_rows, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR), dtype=np.uint8)

    def _diff(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)

    out_orig = list(selected_orig)
    out_rows = [dict(r) for r in selected_rows]
    total_inserted = 0

    cached: dict[str, np.ndarray] = {}

    for _ in range(max_rounds):
        selected_set = {p.name for p in out_orig}
        inserted_round: list[tuple[int, Path, dict[str, int | float | str]]] = []

        for i in range(len(out_rows) - 1):
            left = out_rows[i]
            right = out_rows[i + 1]
            t1 = float(left.get("timestamp_sec", 0.0))
            t2 = float(right.get("timestamp_sec", 0.0))
            if t2 - t1 < min_gap_sec:
                continue

            left_path = out_orig[i]
            right_path = out_orig[i + 1]
            if left_path.name not in cached:
                cached[left_path.name] = _load(left_path)
            if right_path.name not in cached:
                cached[right_path.name] = _load(right_path)
            a_left = cached[left_path.name]
            a_right = cached[right_path.name]

            candidates = [
                r
                for r in frame_rows
                if t1 + 2.0 <= float(r.get("timestamp_sec", 0.0)) <= t2 - 2.0 and str(r.get("frame_name", "")) not in selected_set
            ]
            if not candidates:
                continue

            step = max(1, len(candidates) // 20)
            sampled = candidates[::step]

            best_row = None
            best_score = -1.0
            best_path = None
            for row in sampled:
                name = str(row.get("frame_name", ""))
                if not name:
                    continue
                cand_path = frames_raw_dir / name
                if not cand_path.exists() or _is_blank_transition_frame(cand_path):
                    continue
                if name not in cached:
                    cached[name] = _load(cand_path)
                arr = cached[name]
                score = min(_diff(arr, a_left), _diff(arr, a_right))
                if score > best_score:
                    best_score = score
                    best_row = row
                    best_path = cand_path

            if best_row is None or best_path is None or best_score < novelty_th:
                continue

            selected_set.add(best_path.name)
            inserted_round.append((i + 1, best_path, dict(best_row)))

        if not inserted_round:
            break

        shift = 0
        for pos, path, row in inserted_round:
            out_orig.insert(pos + shift, path)
            out_rows.insert(pos + shift, row)
            shift += 1
        total_inserted += len(inserted_round)

    paired = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0.0)))
    out_orig = [p for p, _ in paired]
    out_rows = [dict(r) for _, r in paired]
    for page, row in enumerate(out_rows, start=1):
        row["page"] = page
    return out_orig, out_rows, total_inserted


def _complete_pages(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    frame_rows: list[dict[str, int | float | str]],
    frames_raw_dir: Path,
    mode: str = "iterative",
    lookahead_sec: float = 30.0,
    dark_cover_th: float = 0.75,
    max_neg: float = 0.012,
    min_diff: float = 0.008,
    max_diff: float = 0.15,
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    """Replace each selected page with its most-complete reveal state.

    Looks up to *lookahead_sec* seconds ahead of each selected page for a
    frame that preserves existing dark content (dark_cover >= dark_cover_th)
    while being *more* complete (additive-only change, diff in [min_diff, max_diff]).
    Replaces the current page with the most-complete such frame found.
    Bounded by the midpoint to the next selected page so we never steal
    a frame that belongs to the next slide.
    """
    if not selected_orig:
        return selected_orig, selected_rows, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(
            Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )

    cache: dict[str, np.ndarray] = {}
    # Freeze original neighbors so one page's replacement does not affect
    # another page's completion window.
    base_orig = list(selected_orig)
    base_rows = [dict(r) for r in selected_rows]

    out_orig = list(selected_orig)
    out_rows = [dict(r) for r in selected_rows]
    completed = 0

    for i, (page_path, page_row) in enumerate(zip(base_orig, base_rows)):
        t_base = float(page_row.get("timestamp_sec", 0.0))
        # Upper bound: midpoint to next selected page, or lookahead, whichever is smaller.
        if i + 1 < len(base_rows):
            t_next = float(base_rows[i + 1].get("timestamp_sec", t_base + lookahead_sec * 2))
            t_limit = min(t_base + lookahead_sec, (t_base + t_next) / 2)
        else:
            t_limit = t_base + lookahead_sec
        if t_limit <= t_base + 1.0:
            continue  # pages too close, nothing to look ahead

        current_path = page_path
        current_row = dict(page_row)
        changed = False
        local_used: set[str] = {current_path.name}

        # Iteratively advance within this page's own completion window.
        # In single-pass mode, run this loop at most once for A/B comparison.
        while True:
            t_current = float(current_row.get("timestamp_sec", 0.0))
            if current_path.name not in cache:
                cache[current_path.name] = _load(current_path)
            a_page = cache[current_path.name]

            candidates = [
                r for r in frame_rows
                if t_current + 1.0 < float(r.get("timestamp_sec", 0.0)) <= t_limit
            ]
            if not candidates:
                break

            best_path: Path | None = None
            best_diff = -1.0
            best_row: dict[str, int | float | str] | None = None

            for row in candidates:
                cname = str(row.get("frame_name", ""))
                if not cname or cname in local_used:
                    continue
                cpath = frames_raw_dir / cname
                if not cpath.exists() or _is_blank_transition_frame(cpath):
                    continue
                if cname not in cache:
                    cache[cname] = _load(cpath)
                arr = cache[cname]
                d = float(np.mean(np.abs(a_page.astype(np.float32) - arr.astype(np.float32))) / 255.0)
                if d < min_diff or d > max_diff:
                    continue
                neg, _pos = _directional_change(a_page, arr)
                if neg > max_neg:
                    continue
                dc, _da = _dark_cover(a_page, arr)
                if dc < dark_cover_th:
                    continue
                if d > best_diff:
                    best_diff = d
                    best_path = cpath
                    best_row = dict(row)

            if best_path is None or best_row is None:
                break

            current_path = best_path
            current_row = best_row
            local_used.add(current_path.name)
            changed = True

            if mode == "single-pass":
                break

        if changed:
            out_orig[i] = current_path
            out_rows[i] = current_row
            out_rows[i]["page"] = page_row["page"]
            completed += 1

    return out_orig, out_rows, completed


def _postprocess_additive_state_machine(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    max_neg: float = 0.0008,
    min_dark_cover: float = 0.60,
    max_dark_add: float = 0.35,
    max_diff: float = 0.10,
) -> tuple[list[Path], list[dict[str, int | float | str]], int, int]:
    """Single state-machine postprocess for progressive reveal slides.

    Rule:
    - walk pages in timeline order
    - skip blank/transition pages
    - maintain a current candidate page
    - if current page differs from candidate by mostly additive change,
      replace candidate with current page (keep the more complete reveal)
    - otherwise, finalize candidate and start a new one
    """
    if not selected_orig:
        return selected_orig, selected_rows, 0, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(
            Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )

    paired = sorted(zip(selected_orig, selected_rows), key=lambda it: float(it[1].get("timestamp_sec", 0.0)))

    # First filter: drop blank transition pages from consideration.
    valid: list[tuple[Path, dict[str, int | float | str]]] = []
    dropped_blank = 0
    for p, r in paired:
        if _is_blank_transition_frame(p):
            dropped_blank += 1
            continue
        valid.append((p, dict(r)))

    if not valid:
        return [], [], 0, dropped_blank

    cache: dict[str, np.ndarray] = {}

    def _get(path: Path) -> np.ndarray:
        if path.name not in cache:
            cache[path.name] = _load(path)
        return cache[path.name]

    out: list[tuple[Path, dict[str, int | float | str]]] = []
    collapsed = 0

    cand_p, cand_r = valid[0]
    cand_a = _get(cand_p)

    for cur_p, cur_r in valid[1:]:
        cur_a = _get(cur_p)
        d = float(np.mean(np.abs(cand_a.astype(np.float32) - cur_a.astype(np.float32))) / 255.0)
        neg, _pos = _directional_change(cand_a, cur_a)
        dc, da = _dark_cover(cand_a, cur_a)

        additive_only = (
            d <= max_diff
            and neg <= max_neg
            and dc >= min_dark_cover
            and da <= max_dark_add
        )

        if additive_only:
            # Replace with the more complete (later) reveal state.
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a
            collapsed += 1
        else:
            out.append((cand_p, cand_r))
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a

    out.append((cand_p, cand_r))

    out_orig = [p for p, _ in out]
    out_rows = [dict(r) for _, r in out]
    for page, row in enumerate(out_rows, start=1):
        row["page"] = page
    return out_orig, out_rows, collapsed, dropped_blank


def _rescue_missing_candidate_pages(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    frame_rows: list[dict[str, int | float | str]],
    frames_raw_dir: Path,
    min_gap_sec: float = 18.0,
    min_diff_to_ends: float = 0.08,
    min_score: float = 0.03,
    min_std: float = 12.0,
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    """Insert one strong missing-page candidate inside wide adjacent gaps.

    Heuristic:
    - scan non-selected frames between two selected pages when time gap is wide
    - candidate should differ from both ends (not a near-copy of either side)
    - choose the candidate with highest separation score
    """
    if len(selected_orig) < 2:
        return selected_orig, selected_rows, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(
            Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )

    by_ts = sorted(frame_rows, key=lambda r: float(r.get("timestamp_sec", 0.0)))
    selected_names = {p.name for p in selected_orig}
    cache: dict[str, np.ndarray] = {}

    def _load_name(name: str) -> np.ndarray | None:
        if not name:
            return None
        if name not in cache:
            p = frames_raw_dir / name
            if not p.exists():
                return None
            cache[name] = _load(p)
        return cache[name]

    inserts: list[tuple[int, Path, dict[str, int | float | str]]] = []

    for i in range(len(selected_rows) - 1):
        a = selected_rows[i]
        b = selected_rows[i + 1]
        ta = float(a.get("timestamp_sec", 0.0))
        tb = float(b.get("timestamp_sec", 0.0))
        if tb - ta < min_gap_sec:
            continue

        an = str(a.get("frame_name", ""))
        bn = str(b.get("frame_name", ""))
        aa = _load_name(an)
        bb = _load_name(bn)
        if aa is None or bb is None:
            continue
        d_ab = float(np.mean(np.abs(aa.astype(np.float32) - bb.astype(np.float32))) / 255.0)

        best: tuple[float, dict[str, int | float | str]] | None = None
        for row in by_ts:
            t = float(row.get("timestamp_sec", 0.0))
            if t <= ta + 1.0 or t >= tb - 1.0:
                continue
            name = str(row.get("frame_name", ""))
            if not name or name in selected_names:
                continue
            cc = _load_name(name)
            if cc is None:
                continue
            if float(cc.astype(np.float32).std()) < min_std:
                continue

            d_ac = float(np.mean(np.abs(aa.astype(np.float32) - cc.astype(np.float32))) / 255.0)
            d_cb = float(np.mean(np.abs(cc.astype(np.float32) - bb.astype(np.float32))) / 255.0)
            if d_ac < min_diff_to_ends or d_cb < min_diff_to_ends:
                continue
            score = min(d_ac, d_cb) - 0.5 * d_ab
            if score < min_score:
                continue
            if best is None or score > best[0]:
                best = (score, row)

        if best is not None:
            row = dict(best[1])
            cname = str(row.get("frame_name", ""))
            cpath = frames_raw_dir / cname
            if cpath.exists():
                inserts.append((i + 1, cpath, row))
                selected_names.add(cname)

    if not inserts:
        return selected_orig, selected_rows, 0

    out_orig = list(selected_orig)
    out_rows = [dict(r) for r in selected_rows]
    offset = 0
    for idx, p, r in inserts:
        out_orig.insert(idx + offset, p)
        out_rows.insert(idx + offset, r)
        offset += 1

    paired = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0.0)))
    out_orig = [p for p, _ in paired]
    out_rows = [dict(r) for _, r in paired]
    for page, row in enumerate(out_rows, start=1):
        row["page"] = page

    return out_orig, out_rows, len(inserts)


def _cleanup_close_pairs(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    diff_th: float = 0.012,
    max_neg: float = 0.002,
    dark_cover_th: float = 0.94,
    dark_add_max: float = 0.05,
    tiny_diff_th: float = 0.003,
    tiny_max_neg: float = 0.001,
    tiny_max_dt: float = 8.0,
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    """
    Post-processing cleanup for only near-exact adjacent duplicates.

    Gap rescue and completion can reintroduce a few almost-identical neighbors.
    Keep this pass intentionally strict so we do not collapse legitimate
    progressive-reveal pages and undercount the final deck.
    """
    if len(selected_orig) < 2:
        return selected_orig, selected_rows, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(
            Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )

    cache: dict[str, np.ndarray] = {}
    to_remove: set[int] = set()
    merged = 0

    i = 0
    while i < len(selected_orig) - 1:
        path_curr = selected_orig[i]
        path_next = selected_orig[i + 1]

        if path_curr.name not in cache:
            cache[path_curr.name] = _load(path_curr)
        if path_next.name not in cache:
            cache[path_next.name] = _load(path_next)

        arr_curr = cache[path_curr.name]
        arr_next = cache[path_next.name]

        # Check Stage E primary: direct pixel-change similarity.
        d = float(np.mean(np.abs(arr_curr.astype(np.float32) - arr_next.astype(np.float32))) / 255.0)

        neg, _pos = _directional_change(arr_curr, arr_next)
        dc, da = _dark_cover(arr_curr, arr_next)
        dt = float(selected_rows[i + 1].get("timestamp_sec", 0.0)) - float(selected_rows[i].get("timestamp_sec", 0.0))
        strict_near_exact = d <= diff_th and neg <= max_neg and dc >= dark_cover_th and da <= dark_add_max
        tiny_near_exact = d <= tiny_diff_th and neg <= tiny_max_neg and dt <= tiny_max_dt
        should_merge = strict_near_exact or tiny_near_exact

        if should_merge:
            # Mark the current (older) page for removal; keep the next.
            to_remove.add(i)
            merged += 1
            # Skip over the next page too; continue with the page after.
            i += 2
        else:
            i += 1

    # Build new lists, excluding removed indices.
    new_orig = [p for i, p in enumerate(selected_orig) if i not in to_remove]
    new_rows = [r for i, r in enumerate(selected_rows) if i not in to_remove]

    # Reindex page numbers.
    for page, row in enumerate(new_rows, start=1):
        row["page"] = page

    return new_orig, new_rows, merged


def _confidence_refill_pages(
    selected_orig: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    frame_rows: list[dict[str, int | float | str]],
    frames_raw_dir: Path,
    max_k: int = 8,
    min_gap_sec: float = 15.0,
    min_group_frames: int = 2,
    ep_prune_diff: float = 0.07,
    ep_prune_neg: float = 0.008,
    max_rounds: int = 2,
    # Legacy params kept for call-site compat; unused.
    gap_factor: float = 2.5,
    novelty_th: float = 0.0,
    strong_first_th: float = 0.0,
    secondary_novelty_th: float = 0.0,
    bridge_near_min: float = 0.0,
    bridge_near_max: float = 0.0,
    bridge_far_min: float = 0.0,
    bridge_far_near_ratio: float = 0.0,
) -> tuple[list[Path], list[dict[str, int | float | str]], int]:
    """Post-FSM adaptive refill for wide transition gaps.

    Uses a unified mini-FSM walk through gap candidates to group progressive-
    reveal chains, keeping only the last (most-complete) frame per group.
    Groups whose representative is too close to either endpoint (additive or
    diff <= ep_prune_diff) are pruned.  Single-frame groups are dropped as noise.

    Gate: dt >= min_gap_sec.  Content-based filtering is handled entirely by
    endpoint proximity pruning — no time-based bridge gate needed.

    Runs after the main FSM so inserted frames are never re-collapsed.
    """
    if len(selected_orig) < 2:
        return selected_orig, selected_rows, 0

    def _load(path: Path) -> np.ndarray:
        return np.asarray(
            Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
            dtype=np.uint8,
        )

    def _diff(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)

    def _is_additive(prev: np.ndarray, curr: np.ndarray) -> bool:
        """Check if curr is a progressive reveal of prev."""
        d = _diff(prev, curr)
        if d > 0.10:
            return False
        neg, _ = _directional_change(prev, curr)
        if neg > 0.002:
            return False
        dc, da = _dark_cover(prev, curr)
        return dc >= 0.60 and da <= 0.35

    cache: dict[str, np.ndarray] = {}
    by_ts = sorted(frame_rows, key=lambda r: float(r.get("timestamp_sec", 0.0)))
    curr_orig = list(selected_orig)
    curr_rows = [dict(r) for r in selected_rows]
    total_inserted = 0

    for _round in range(max_rounds):
        times = [float(r.get("timestamp_sec", 0.0)) for r in curr_rows]
        pos_gaps = [times[j + 1] - times[j] for j in range(len(times) - 1) if times[j + 1] > times[j]]
        if not pos_gaps:
            break

        selected_names: set[str] = {p.name for p in curr_orig}
        inserts: list[tuple[int, list[tuple[Path, dict[str, int | float | str]]]]] = []

        for i in range(len(curr_rows) - 1):
            t_a = times[i]
            t_b = times[i + 1]
            dt = t_b - t_a

            p_a, p_b = curr_orig[i], curr_orig[i + 1]
            if p_a.name not in cache:
                cache[p_a.name] = _load(p_a)
            if p_b.name not in cache:
                cache[p_b.name] = _load(p_b)
            a_left = cache[p_a.name]
            a_right = cache[p_b.name]

            # Universal time gate: skip trivially short gaps.
            if dt < min_gap_sec:
                continue

            # Gather candidate frames strictly inside the gap.
            candidates: list[tuple[Path, dict[str, int | float | str]]] = []
            for row in by_ts:
                t = float(row.get("timestamp_sec", 0.0))
                if t <= t_a + 1.0 or t >= t_b - 1.0:
                    continue
                name = str(row.get("frame_name", ""))
                if not name or name in selected_names:
                    continue
                cpath = frames_raw_dir / name
                if not cpath.exists() or _is_blank_transition_frame(cpath):
                    continue
                candidates.append((cpath, dict(row)))

            if not candidates:
                continue

            # Sub-sample to cap image-loading cost.
            step = max(1, len(candidates) // 60)
            sampled = candidates[::step]
            for cp, _ in sampled:
                if cp.name not in cache:
                    cache[cp.name] = _load(cp)

            # --- Mini-FSM walk: group consecutive additive frames ---
            # Fix 1: only check previous frame (current_rep), not group_base
            groups: list[list[tuple[Path, dict[str, int | float | str]]]] = []
            current_group: list[tuple[Path, dict[str, int | float | str]]] = []

            for cp, row in sampled:
                if cp.name in selected_names:
                    continue
                arr = cache[cp.name]
                is_add_to_rep = bool(
                    current_group and _is_additive(cache[current_group[-1][0].name], arr)
                )
                if is_add_to_rep:
                    current_group.append((cp, row))
                else:
                    if current_group:
                        groups.append(current_group)
                    current_group = [(cp, row)]

            if current_group:
                groups.append(current_group)

            # Each group's representative is its last frame (most complete).
            # Prune groups whose rep is too close to either endpoint:
            #  - canonical additive check (strict)
            #  - proximity check: diff <= ep_prune_diff AND neg <= ep_prune_neg
            #    catches borderline intermediates that barely fail _is_additive
            #    (e.g. da=0.355 > 0.35) while preserving legitimate fills that
            #    have low diff but high neg (content replacement, not reveal).
            picked: list[tuple[Path, dict[str, int | float | str]]] = []
            for grp in groups:
                if len(grp) < min_group_frames:
                    continue
                rep_cp, rep_row = grp[-1]
                rep_arr = cache[rep_cp.name]
                # Right endpoint pruning
                if _is_additive(rep_arr, a_right):
                    continue
                d_r = _diff(rep_arr, a_right)
                if d_r <= ep_prune_diff:
                    neg_r, _ = _directional_change(rep_arr, a_right)
                    if neg_r <= ep_prune_neg:
                        continue  # borderline reveal of right endpoint
                # Left endpoint pruning (first group only)
                if not picked:
                    if _is_additive(a_left, rep_arr):
                        continue
                    d_l = _diff(a_left, rep_arr)
                    if d_l <= ep_prune_diff:
                        neg_l, _ = _directional_change(a_left, rep_arr)
                        if neg_l <= ep_prune_neg:
                            continue  # borderline completion of left endpoint
                picked.append((rep_cp, dict(rep_row)))
                selected_names.add(rep_cp.name)

            # Cap at max_k, preferring groups whose reps are most novel.
            if len(picked) > max_k:
                scored = sorted(
                    picked,
                    key=lambda pr: -min(
                        _diff(cache[pr[0].name], a_left),
                        _diff(cache[pr[0].name], a_right),
                    ),
                )
                for cp, _ in scored[max_k:]:
                    selected_names.discard(cp.name)
                picked = scored[:max_k]

            if picked:
                inserts.append((i + 1, picked))

        if not inserts:
            break

        out_orig = list(curr_orig)
        out_rows = [dict(r) for r in curr_rows]
        offset = 0
        for base_idx, picks in inserts:
            for j, (cp, row) in enumerate(picks):
                out_orig.insert(base_idx + offset + j, cp)
                out_rows.insert(base_idx + offset + j, row)
            offset += len(picks)

        paired = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0.0)))
        curr_orig = [p for p, _ in paired]
        curr_rows = [dict(r) for _, r in paired]
        for page, row in enumerate(curr_rows, start=1):
            row["page"] = page

        round_inserted = sum(len(picks) for _, picks in inserts)
        total_inserted += round_inserted
        if round_inserted <= 0:
            break

    return curr_orig, curr_rows, total_inserted


def run_pipeline(
    url: str,
    outdir: Path,
    task_id: str | None,
    no_download: bool,
    fps: float,
    download_retries: int,
    mask_config: Path | None,
    ocr_lang: str,
    skip_ocr: bool,
    refill_multiplier: float,
    max_refill_windows: int,
    refill_window_cap_sec: float,
    complete_mode: str,
    gap_refill_mode: str,
) -> int:
    if not url.startswith("http"):
        print("ERROR: --url must be a valid http(s) URL")
        return 2
    if fps <= 0:
        print("ERROR: --fps must be > 0")
        return 2

    tid = task_id or make_task_id("slide")
    paths = build_task_paths(outdir, tid)
    ensure_task_dirs(paths)

    manifest = TaskManifest(task_id=tid, url=url, outdir=str(outdir), task_dir=str(paths.task_dir))
    manifest.transition(TaskStatus.CREATED, "task created and directories prepared")
    write_manifest(manifest, paths.manifest_path)

    manifest.transition(TaskStatus.DOWNLOADING, "starting download step")
    write_manifest(manifest, paths.manifest_path)

    frame_manifest_path: Path | None = None

    if no_download:
        manifest.metadata["download"] = {"mode": "no-download", "ok": True}
        manifest.transition(TaskStatus.EXTRACTING, "download skipped by --no-download")
        manifest.metadata["extract"] = {"ok": False, "skipped": True, "reason": "no-download mode"}
    else:
        ok, msg = _download_video(url, paths.video_dir, retries=download_retries)
        manifest.metadata["download"] = {"mode": "yt-dlp", "ok": ok, "message": msg}
        if not ok:
            manifest.transition(TaskStatus.FAILED, f"download failed: {msg}")
            write_manifest(manifest, paths.manifest_path)
            print(f"Task failed: {msg}")
            print(f"Manifest: {paths.manifest_path}")
            return 1

        video_path = find_downloaded_video(paths.video_dir)
        if video_path is None:
            msg = "no downloaded video file found in video directory"
            manifest.transition(TaskStatus.FAILED, msg)
            write_manifest(manifest, paths.manifest_path)
            print(f"Task failed: {msg}")
            print(f"Manifest: {paths.manifest_path}")
            return 1

        manifest.metadata["download"]["video_path"] = str(video_path)
        manifest.transition(TaskStatus.EXTRACTING, "download completed, starting frame extraction")
        write_manifest(manifest, paths.manifest_path)

        extract_ok, extract_msg = _extract_frames(video_path=video_path, frames_dir=paths.frames_raw_dir, fps=fps)
        if not extract_ok:
            manifest.metadata["extract"] = {"ok": False, "message": extract_msg, "fps": fps}
            manifest.transition(TaskStatus.FAILED, f"frame extraction failed: {extract_msg}")
            write_manifest(manifest, paths.manifest_path)
            print(f"Task failed: {extract_msg}")
            print(f"Manifest: {paths.manifest_path}")
            return 1

        frame_paths = sorted(paths.frames_raw_dir.glob("frame_*.jpg"))
        frame_rows = build_frame_rows(frame_paths=frame_paths, fps=fps)
        frame_manifest_path = paths.artifacts_dir / "frame_manifest.json"
        write_frame_manifest(path=frame_manifest_path, fps=fps, frame_rows=frame_rows)
        manifest.metadata["extract"] = {
            "ok": True,
            "message": extract_msg,
            "fps": fps,
            "frame_count": len(frame_rows),
            "frame_manifest": str(frame_manifest_path),
        }

    selected_rows: list[dict[str, int | float | str]] = []
    if frame_manifest_path is not None and frame_manifest_path.exists():
        manifest.transition(TaskStatus.PREPROCESSING, "starting D3 preprocessing")
        write_manifest(manifest, paths.manifest_path)

        video_path_str = str(manifest.metadata.get("download", {}).get("video_path", ""))
        video_path = Path(video_path_str) if video_path_str else None
        frame_paths = sorted(paths.frames_raw_dir.glob("frame_*.jpg"))
        mask_profile = load_mask_profile(mask_config)
        mask_profile_path = paths.artifacts_dir / "mask_profile.json"
        write_mask_profile(mask_profile_path, mask_profile)
        norm_paths = preprocess_frames(frame_paths, paths.frames_norm_dir, mask_profile)
        manifest.metadata["preprocess"] = {
            "ok": True,
            "input_frames": len(frame_paths),
            "output_frames": len(norm_paths),
            "mask_profile": str(mask_profile_path),
        }

        manifest.transition(TaskStatus.DEDUPING, "starting D4/D5 dedupe")
        write_manifest(manifest, paths.manifest_path)

        selected_norm, dedupe_stats = dedupe_frames(norm_paths, DedupeConfig())
        selected_orig: list[Path] = []
        for p in selected_norm:
            src = paths.frames_raw_dir / p.name
            if src.exists():
                selected_orig.append(src)

        selected_dir = paths.artifacts_dir / "selected"
        selected_dir.mkdir(parents=True, exist_ok=True)
        for src in selected_orig:
            shutil.copy(src, selected_dir / src.name)

        frame_rows = _load_frame_rows(frame_manifest_path)
        selected_rows = _rows_for_selected(selected_orig, frame_rows)
        manifest.metadata["dedupe"] = {
            "ok": True,
            "stats": dedupe_stats,
            "selected_count": len(selected_orig),
            "selected_dir": str(selected_dir),
        }

        # D6 OCR + D7 refill (scene-driven windows first, OCR windows secondary)
        ocr_report_path = paths.artifacts_dir / "ocr_report.json"
        selected_norm_for_selected = [paths.frames_norm_dir / p.name for p in selected_orig if (paths.frames_norm_dir / p.name).exists()]
        scene_windows = detect_scene_driven_windows(selected_norm_for_selected, selected_rows)

        if skip_ocr:
            signals = []
            ocr_windows = []
        else:
            signals = run_ocr_signals(selected_orig, lang=ocr_lang)
            ocr_windows = detect_suspect_windows(selected_rows, signals)

        windows = _merge_windows(scene_windows, ocr_windows)

        refill_meta: dict[str, object] = {
            "attempted": False,
            "refill_multiplier": refill_multiplier,
            "max_refill_windows": max_refill_windows,
            "refill_window_cap_sec": refill_window_cap_sec,
            "merged_input": len(selected_orig),
            "merged_output": len(selected_orig),
            "windows_considered": len(windows),
            "windows_expanded": 0,
            "scene_windows": len(scene_windows),
            "ocr_windows": len(ocr_windows),
        }

        if (
            windows
            and video_path is not None
            and video_path.exists()
            and refill_multiplier > 1.0
            and max_refill_windows > 0
        ):
            refill_meta["attempted"] = True
            refill_fps = max(fps * refill_multiplier, fps + 1.0)
            refill_meta["refill_fps"] = refill_fps

            refill_raw_dir = paths.artifacts_dir / "refill_raw"
            refill_norm_dir = paths.artifacts_dir / "refill_norm"
            refill_raw_all: list[Path] = []
            refill_rows_all: list[dict[str, int | float | str]] = []
            errors: list[str] = []

            expanded: list[tuple[float, float]] = []
            for win in windows:
                start_ts = max(0.0, float(win.get("start_ts", 0.0)) - 0.8)
                end_ts = float(win.get("end_ts", start_ts + 2.0)) + 0.8
                expanded.extend(split_window_ranges(start_ts, end_ts, refill_window_cap_sec, overlap_sec=1.0))
                if len(expanded) >= max_refill_windows:
                    break
            expanded = expanded[:max_refill_windows]
            refill_meta["windows_expanded"] = len(expanded)

            for widx, (start_ts, end_ts) in enumerate(expanded, start=1):
                ok_refill, msg_refill, refill_frames = extract_refill_window_frames(
                    video_path=video_path,
                    window_idx=widx,
                    start_sec=start_ts,
                    end_sec=end_ts,
                    fps=refill_fps,
                    out_dir=refill_raw_dir,
                )
                if not ok_refill:
                    errors.append(msg_refill)
                    continue
                refill_raw_all.extend(refill_frames)
                refill_rows_all.extend(refill_rows_for_window(refill_frames, start_sec=start_ts, fps=refill_fps))

            if refill_raw_all:
                preprocess_frames(refill_raw_all, refill_norm_dir, mask_profile)
                selected_orig, selected_rows, merge_stats = _merge_with_refill_and_rededupe(
                    selected_rows=selected_rows,
                    selected_orig=selected_orig,
                    selected_norm_dir=paths.frames_norm_dir,
                    refill_rows=refill_rows_all,
                    refill_raw_paths=refill_raw_all,
                    refill_norm_dir=refill_norm_dir,
                    work_dir=paths.artifacts_dir,
                    cfg=DedupeConfig(),
                )
                refill_meta.update(merge_stats)
                refill_meta["refill_frames"] = len(refill_raw_all)
                refill_meta["refill_rows"] = len(refill_rows_all)
                refill_meta["errors"] = errors

                # Re-run OCR signals and windows after merge.
                if not skip_ocr:
                    signals = run_ocr_signals(selected_orig, lang=ocr_lang)
                    ocr_windows = detect_suspect_windows(selected_rows, signals)
                else:
                    ocr_windows = []
                selected_norm_for_selected = [paths.frames_norm_dir / p.name for p in selected_orig if (paths.frames_norm_dir / p.name).exists()]
                scene_windows = detect_scene_driven_windows(selected_norm_for_selected, selected_rows)
                windows = _merge_windows(scene_windows, ocr_windows)
                refill_meta["scene_windows_after"] = len(scene_windows)
                refill_meta["ocr_windows_after"] = len(ocr_windows)
            else:
                refill_meta["errors"] = errors
                refill_meta["refill_frames"] = 0
                refill_meta["refill_rows"] = 0

        selected_orig, selected_rows, rescued_gap = _rescue_gap_pages(
            selected_orig=selected_orig,
            selected_rows=selected_rows,
            frame_rows=frame_rows,
            frames_raw_dir=paths.frames_raw_dir,
        )
        refill_meta["rescued_gap_pages"] = rescued_gap
        selected_orig, selected_rows, completed_pages = _complete_pages(
            selected_orig=selected_orig,
            selected_rows=selected_rows,
            frame_rows=frame_rows,
            frames_raw_dir=paths.frames_raw_dir,
            mode=complete_mode,
        )
        refill_meta["completed_pages"] = completed_pages
        refill_meta["complete_mode"] = complete_mode
        selected_orig, selected_rows, fsm_collapsed, fsm_dropped_blank = _postprocess_additive_state_machine(
            selected_orig=selected_orig,
            selected_rows=selected_rows,
        )
        refill_meta["fsm_collapsed_pages"] = fsm_collapsed
        refill_meta["dropped_blank_pages"] = fsm_dropped_blank
        confidence_refilled = 0
        if gap_refill_mode == "confidence":
            selected_orig, selected_rows, confidence_refilled = _confidence_refill_pages(
                selected_orig=selected_orig,
                selected_rows=selected_rows,
                frame_rows=frame_rows,
                frames_raw_dir=paths.frames_raw_dir,
            )
        refill_meta["gap_refill_mode"] = gap_refill_mode
        refill_meta["confidence_refilled_pages"] = confidence_refilled
        selected_orig, selected_rows, merged_close_pairs = _cleanup_close_pairs(
            selected_orig=selected_orig,
            selected_rows=selected_rows,
        )
        refill_meta["merged_close_pairs"] = merged_close_pairs
        write_ocr_report(ocr_report_path, signals, windows)
        manifest.metadata["ocr"] = {
            "ok": not skip_ocr,
            "skip_ocr": skip_ocr,
            "lang": ocr_lang,
            "signal_count": len(signals),
            "suspect_windows": len(windows),
            "report": str(ocr_report_path),
            "refill": refill_meta,
        }
        manifest.metadata["dedupe"]["selected_count"] = len(selected_orig)
        manifest.metadata["dedupe"]["dropped_blank_pages"] = int(refill_meta.get("dropped_blank_pages", 0))
        manifest.metadata["dedupe"]["rescued_gap_pages"] = int(refill_meta.get("rescued_gap_pages", 0))
        manifest.metadata["dedupe"]["completed_pages"] = int(refill_meta.get("completed_pages", 0))
        manifest.metadata["dedupe"]["complete_mode"] = str(refill_meta.get("complete_mode", "iterative"))
        manifest.metadata["dedupe"]["fsm_collapsed_pages"] = int(refill_meta.get("fsm_collapsed_pages", 0))
        manifest.metadata["dedupe"]["gap_refill_mode"] = str(refill_meta.get("gap_refill_mode", "none"))
        manifest.metadata["dedupe"]["confidence_refilled_pages"] = int(refill_meta.get("confidence_refilled_pages", 0))
        manifest.metadata["dedupe"]["merged_close_pairs"] = int(refill_meta.get("merged_close_pairs", 0))

        manifest.transition(TaskStatus.RENDERING, "starting D8 rendering")
        write_manifest(manifest, paths.manifest_path)

        pdf_a = paths.pdf_dir / "slides.pdf"
        pdf_b = paths.pdf_dir / "slides_with_index.pdf"
        pdf_raw = paths.pdf_dir / "slides_raw.pdf"
        if selected_orig:
            render_pdf_a(selected_orig, pdf_a)
            render_pdf_b_with_index(selected_orig, selected_rows, source_url=url, out_pdf=pdf_b)
        # Raw comparison PDF: all extracted frames before any deduplication.
        raw_frames_for_pdf = sorted(paths.frames_raw_dir.glob("frame_*.jpg"))
        if raw_frames_for_pdf:
            render_pdf_raw(raw_frames_for_pdf, pdf_raw)

        slides_json = paths.artifacts_dir / "slides.json"
        write_slides_json(slides_json, selected_rows)
        manifest.metadata["render"] = {
            "ok": bool(selected_orig),
            "pdf_a": str(pdf_a),
            "pdf_b": str(pdf_b),
            "pdf_raw": str(pdf_raw),
            "raw_frame_count": len(raw_frames_for_pdf),
            "slides_json": str(slides_json),
        }

        # D9 quality gate
        metrics = compute_quality_metrics(
            raw_count=len(frame_paths),
            selected_count=len(selected_orig),
            suspect_windows=len(windows),
        )
        gated = evaluate_gate(metrics)
        quality_json = paths.artifacts_dir / "quality_report.json"
        quality_md = paths.artifacts_dir / "quality_report.md"
        write_quality_report(quality_json, gated)
        write_quality_markdown(quality_md, gated)
        manifest.metadata["quality"] = {
            "report_json": str(quality_json),
            "report_md": str(quality_md),
            **gated,
        }

    manifest.transition(TaskStatus.DONE, "day-10 scaffold pipeline complete")
    write_manifest(manifest, paths.manifest_path)

    print(f"Task done: {tid}")
    print(f"Task dir: {paths.task_dir}")
    print(f"Manifest: {paths.manifest_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="YouTube slides MVP pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run", help="run full MVP scaffold pipeline (D2-D10)")
    run_cmd.add_argument("--url", required=True, help="YouTube URL")
    run_cmd.add_argument("--outdir", default="./runs", help="output root directory")
    run_cmd.add_argument("--task-id", default=None, help="optional task id")
    run_cmd.add_argument("--no-download", action="store_true", help="skip yt-dlp download")
    run_cmd.add_argument("--fps", type=float, default=1.0, help="frame extraction rate (frames/sec)")
    run_cmd.add_argument("--download-retries", type=int, default=2, help="download retries per format")
    run_cmd.add_argument("--mask-config", default=None, help="optional JSON file overriding mask profile")
    run_cmd.add_argument("--ocr-lang", default="eng+chi_sim", help="pytesseract language string")
    run_cmd.add_argument("--skip-ocr", action="store_true", help="skip OCR stage")
    run_cmd.add_argument("--refill-multiplier", type=float, default=2.5, help="D7 refill fps multiplier")
    run_cmd.add_argument("--max-refill-windows", type=int, default=3, help="max suspect windows to refill")
    run_cmd.add_argument("--refill-window-cap-sec", type=float, default=60.0, help="max seconds per refill window")
    run_cmd.add_argument(
        "--complete-mode",
        choices=["iterative", "single-pass"],
        default="iterative",
        help="page completion strategy for A/B comparison",
    )
    run_cmd.add_argument(
        "--gap-refill-mode",
        choices=["none", "confidence"],
        default="none",
        help="optional post-FSM adaptive refill mode for wide low-confidence gaps",
    )

    sub.add_parser("healthcheck", help="print tool versions")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "healthcheck":
        return run_healthcheck()
    if args.command == "run":
        return run_pipeline(
            url=args.url,
            outdir=Path(args.outdir).resolve(),
            task_id=args.task_id,
            no_download=bool(args.no_download),
            fps=float(args.fps),
            download_retries=int(args.download_retries),
            mask_config=Path(args.mask_config).resolve() if args.mask_config else None,
            ocr_lang=str(args.ocr_lang),
            skip_ocr=bool(args.skip_ocr),
            refill_multiplier=float(args.refill_multiplier),
            max_refill_windows=int(args.max_refill_windows),
            refill_window_cap_sec=float(args.refill_window_cap_sec),
            complete_mode=str(args.complete_mode),
            gap_refill_mode=str(args.gap_refill_mode),
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
