from __future__ import annotations

import json
from pathlib import Path


def find_downloaded_video(video_dir: Path) -> Path | None:
    patterns = ["*.mp4", "*.mkv", "*.webm", "*.mov", "*.m4v"]
    candidates: list[Path] = []
    for pattern in patterns:
        candidates.extend(video_dir.glob(pattern))
    if not candidates:
        return None
    return sorted(candidates)[0]


def build_frame_rows(frame_paths: list[Path], fps: float) -> list[dict[str, float | int | str]]:
    if fps <= 0:
        raise ValueError("fps must be > 0")

    rows: list[dict[str, float | int | str]] = []
    for idx, frame in enumerate(sorted(frame_paths), start=1):
        ts_sec = (idx - 1) / fps
        rows.append(
            {
                "frame_index": idx,
                "frame_name": frame.name,
                "timestamp_sec": round(ts_sec, 6),
                "timestamp_ms": int(round(ts_sec * 1000)),
            }
        )
    return rows


def write_frame_manifest(path: Path, fps: float, frame_rows: list[dict[str, float | int | str]]) -> None:
    payload = {
        "fps": fps,
        "frame_count": len(frame_rows),
        "frames": frame_rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def read_frame_manifest(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
