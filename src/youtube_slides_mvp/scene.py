from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def _load_gray(path: Path, size: tuple[int, int] = (256, 144)) -> np.ndarray:
    img = Image.open(path).convert("L").resize(size, Image.Resampling.BILINEAR)
    return np.asarray(img, dtype=np.uint8)


def _hash_bits(gray: np.ndarray) -> np.ndarray:
    small = gray.reshape(12, gray.shape[0] // 12, 16, gray.shape[1] // 16).mean(axis=(1, 3))
    return (small > small.mean()).reshape(-1)


def _hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)


def _reveal(prev: np.ndarray, curr: np.ndarray) -> tuple[float, float]:
    pm = prev >= np.percentile(prev, 70)
    cm = curr >= np.percentile(curr, 70)
    prev_n = int(pm.sum())
    curr_n = int(cm.sum())
    if prev_n == 0 or curr_n == 0:
        return 0.0, 1.0
    inter = int(np.logical_and(pm, cm).sum())
    add = int(np.logical_and(~pm, cm).sum())
    return inter / float(prev_n), add / float(curr_n)


def detect_scene_driven_windows(
    selected_norm_paths: list[Path],
    selected_rows: list[dict[str, int | float | str]],
    min_pair_run: int = 4,
    progressive_diff_th: float = 0.05,
    progressive_hash_th: int = 18,
    progressive_cover_th: float = 0.80,
    progressive_add_th: float = 0.45,
    low_motion_diff_th: float = 0.04,
    low_motion_min_pairs: int = 6,
) -> list[dict[str, int | float | str]]:
    if len(selected_norm_paths) < 2 or len(selected_rows) != len(selected_norm_paths):
        return []

    arrays = [_load_gray(p) for p in selected_norm_paths]
    hashes = [_hash_bits(a) for a in arrays]

    windows: list[dict[str, int | float | str]] = []
    run_start = None
    run_pairs = 0
    low_start = None
    low_pairs = 0

    def push_window(start_idx: int, end_idx: int, reason: str, pair_count: int) -> None:
        if pair_count <= 0:
            return
        windows.append(
            {
                "start_ts": selected_rows[start_idx]["timestamp_sec"],
                "end_ts": selected_rows[end_idx]["timestamp_sec"],
                "reason": reason,
                "pair_count": pair_count,
            }
        )

    for i in range(1, len(arrays)):
        d = _diff(arrays[i - 1], arrays[i])
        hd = _hamming(hashes[i - 1], hashes[i])
        cover, add = _reveal(arrays[i - 1], arrays[i])

        progressive = d <= progressive_diff_th and (hd <= progressive_hash_th or (cover >= progressive_cover_th and add <= progressive_add_th))
        low_motion = d <= low_motion_diff_th

        if progressive:
            if run_start is None:
                run_start = i - 1
            run_pairs += 1
        else:
            if run_start is not None and run_pairs >= min_pair_run:
                push_window(run_start, i, "scene-progressive-run", run_pairs)
            run_start = None
            run_pairs = 0

        if low_motion:
            if low_start is None:
                low_start = i - 1
            low_pairs += 1
        else:
            if low_start is not None and low_pairs >= low_motion_min_pairs:
                push_window(low_start, i, "scene-low-motion-run", low_pairs)
            low_start = None
            low_pairs = 0

    if run_start is not None and run_pairs >= min_pair_run:
        push_window(run_start, len(selected_rows) - 1, "scene-progressive-run", run_pairs)
    if low_start is not None and low_pairs >= low_motion_min_pairs:
        push_window(low_start, len(selected_rows) - 1, "scene-low-motion-run", low_pairs)

    # Merge overlapping windows from different scene reasons.
    windows.sort(key=lambda w: float(w["start_ts"]))
    merged: list[dict[str, int | float | str]] = []
    for win in windows:
        s = float(win["start_ts"])
        e = float(win["end_ts"])
        if not merged:
            merged.append(dict(win))
            continue
        ls = float(merged[-1]["start_ts"])
        le = float(merged[-1]["end_ts"])
        if s <= le:
            merged[-1]["end_ts"] = max(le, e)
            merged[-1]["reason"] = "scene-merged"
            merged[-1]["pair_count"] = int(merged[-1].get("pair_count", 0)) + int(win.get("pair_count", 0))
        else:
            merged.append(dict(win))

    return merged
