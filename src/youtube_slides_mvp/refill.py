from __future__ import annotations

import subprocess
from pathlib import Path


def split_window_ranges(start_sec: float, end_sec: float, cap_sec: float, overlap_sec: float = 1.0) -> list[tuple[float, float]]:
    if end_sec <= start_sec:
        return []
    if cap_sec <= 0:
        return [(start_sec, end_sec)]

    ranges: list[tuple[float, float]] = []
    cur = start_sec
    step = max(0.5, cap_sec - max(0.0, overlap_sec))
    while cur < end_sec:
        nxt = min(end_sec, cur + cap_sec)
        ranges.append((cur, nxt))
        if nxt >= end_sec:
            break
        cur += step
    return ranges


def extract_refill_window_frames(
    video_path: Path,
    window_idx: int,
    start_sec: float,
    end_sec: float,
    fps: float,
    out_dir: Path,
) -> tuple[bool, str, list[Path]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / f"w{window_idx:02d}_frame_%06d.jpg"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{max(0.0, start_sec):.3f}",
        "-to",
        f"{max(end_sec, start_sec + 0.5):.3f}",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps}",
        "-q:v",
        "2",
        str(pattern),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "refill extraction failed").strip().splitlines()[-1]
        return False, err, []
    frames = sorted(out_dir.glob(f"w{window_idx:02d}_frame_*.jpg"))
    return True, "ok", frames


def refill_rows_for_window(frames: list[Path], start_sec: float, fps: float) -> list[dict[str, int | float | str]]:
    rows: list[dict[str, int | float | str]] = []
    for i, frame in enumerate(sorted(frames), start=1):
        ts = start_sec + (i - 1) / fps
        rows.append(
            {
                "frame_name": frame.name,
                "timestamp_sec": round(ts, 6),
                "timestamp_ms": int(round(ts * 1000)),
                "source": "refill",
            }
        )
    return rows
