from pathlib import Path

from src.youtube_slides_mvp.refill import refill_rows_for_window, split_window_ranges


def test_refill_rows_for_window_timestamps(tmp_path: Path) -> None:
    frames = []
    for i in range(1, 4):
        p = tmp_path / f"w01_frame_{i:06d}.jpg"
        p.write_text("x", encoding="utf-8")
        frames.append(p)

    rows = refill_rows_for_window(frames, start_sec=10.0, fps=2.0)
    assert rows[0]["timestamp_ms"] == 10000
    assert rows[1]["timestamp_ms"] == 10500
    assert rows[2]["timestamp_ms"] == 11000


def test_split_window_ranges_caps_long_segments() -> None:
    ranges = split_window_ranges(10.0, 160.0, cap_sec=60.0, overlap_sec=1.0)
    assert len(ranges) >= 3
    assert ranges[0][0] == 10.0
    assert ranges[0][1] <= 70.0
    assert ranges[-1][1] == 160.0
