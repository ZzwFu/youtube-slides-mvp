from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from .dedupe import DedupeConfig, dedupe_frames
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
            not skip_ocr
            and windows
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
                signals = run_ocr_signals(selected_orig, lang=ocr_lang)
                selected_norm_for_selected = [paths.frames_norm_dir / p.name for p in selected_orig if (paths.frames_norm_dir / p.name).exists()]
                scene_windows = detect_scene_driven_windows(selected_norm_for_selected, selected_rows)
                ocr_windows = detect_suspect_windows(selected_rows, signals)
                windows = _merge_windows(scene_windows, ocr_windows)
                refill_meta["scene_windows_after"] = len(scene_windows)
                refill_meta["ocr_windows_after"] = len(ocr_windows)
            else:
                refill_meta["errors"] = errors
                refill_meta["refill_frames"] = 0
                refill_meta["refill_rows"] = 0

        selected_orig, selected_rows, dropped_blank = _drop_blank_transition_pages(selected_orig, selected_rows)
        refill_meta["dropped_blank_pages"] = dropped_blank
        selected_orig, selected_rows, rescued_gap = _rescue_gap_pages(
            selected_orig=selected_orig,
            selected_rows=selected_rows,
            frame_rows=frame_rows,
            frames_raw_dir=paths.frames_raw_dir,
        )
        refill_meta["rescued_gap_pages"] = rescued_gap

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
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
