from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.cli import _refill_gaps


def _save(path: Path, value: int) -> None:
    arr = np.full((144, 256), value, dtype=np.uint8)
    Image.fromarray(arr).save(path, format="JPEG")


def test_refill_gaps_rescues_prefix_gap_novelty(tmp_path: Path) -> None:
    f0 = tmp_path / "frame_000001.jpg"
    f10 = tmp_path / "frame_000010.jpg"
    f25 = tmp_path / "frame_000025.jpg"
    f50 = tmp_path / "frame_000050.jpg"
    _save(f0, 100)
    _save(f10, 210)
    _save(f25, 120)
    _save(f50, 160)

    selected_orig = [f25, f50]
    selected_rows = [
        {"page": 1, "frame_name": f25.name, "timestamp_sec": 24.0, "timestamp_ms": 24000},
        {"page": 2, "frame_name": f50.name, "timestamp_sec": 49.0, "timestamp_ms": 49000},
    ]
    frame_rows = [
        {"frame_name": f0.name, "timestamp_sec": 0.0, "timestamp_ms": 0},
        {"frame_name": f10.name, "timestamp_sec": 9.0, "timestamp_ms": 9000},
        {"frame_name": f25.name, "timestamp_sec": 24.0, "timestamp_ms": 24000},
        {"frame_name": f50.name, "timestamp_sec": 49.0, "timestamp_ms": 49000},
    ]

    out_orig, out_rows, inserted = _refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=tmp_path,
        strategy="novelty",
        min_gap_sec=20.0,
        max_rounds=1,
        novelty_th=0.02,
    )

    assert inserted == 1
    assert out_orig[0].name == f10.name
    assert out_rows[0]["frame_name"] == f10.name
    assert [int(r["page"]) for r in out_rows] == [1, 2, 3]


def test_refill_gaps_does_not_rescue_prefix_when_gap_too_short(tmp_path: Path) -> None:
    f0 = tmp_path / "frame_000001.jpg"
    f10 = tmp_path / "frame_000010.jpg"
    f15 = tmp_path / "frame_000015.jpg"
    f50 = tmp_path / "frame_000050.jpg"
    _save(f0, 100)
    _save(f10, 210)
    _save(f15, 120)
    _save(f50, 160)

    selected_orig = [f15, f50]
    selected_rows = [
        {"page": 1, "frame_name": f15.name, "timestamp_sec": 14.0, "timestamp_ms": 14000},
        {"page": 2, "frame_name": f50.name, "timestamp_sec": 49.0, "timestamp_ms": 49000},
    ]
    frame_rows = [
        {"frame_name": f0.name, "timestamp_sec": 0.0, "timestamp_ms": 0},
        {"frame_name": f10.name, "timestamp_sec": 9.0, "timestamp_ms": 9000},
        {"frame_name": f15.name, "timestamp_sec": 14.0, "timestamp_ms": 14000},
        {"frame_name": f50.name, "timestamp_sec": 49.0, "timestamp_ms": 49000},
    ]

    out_orig, out_rows, inserted = _refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=tmp_path,
        strategy="novelty",
        min_gap_sec=20.0,
        max_rounds=1,
        novelty_th=0.02,
    )

    assert inserted == 0
    assert out_orig[0].name == f15.name
    assert out_rows[0]["frame_name"] == f15.name
