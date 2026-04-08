from pathlib import Path

from youtube_slides_mvp.extract import build_frame_rows, find_downloaded_video, write_frame_manifest


def test_build_frame_rows_basic(tmp_path: Path) -> None:
    frames = [tmp_path / "frame_000001.jpg", tmp_path / "frame_000002.jpg", tmp_path / "frame_000003.jpg"]
    for frame in frames:
        frame.write_text("x", encoding="utf-8")

    rows = build_frame_rows(frames, fps=2.0)
    assert len(rows) == 3
    assert rows[0]["timestamp_ms"] == 0
    assert rows[1]["timestamp_ms"] == 500
    assert rows[2]["timestamp_ms"] == 1000


def test_find_downloaded_video(tmp_path: Path) -> None:
    (tmp_path / "video.webm").write_text("x", encoding="utf-8")
    found = find_downloaded_video(tmp_path)
    assert found is not None
    assert found.name == "video.webm"


def test_write_frame_manifest(tmp_path: Path) -> None:
    rows = [
        {"frame_index": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 0.0, "timestamp_ms": 0},
    ]
    out = tmp_path / "frame_manifest.json"
    write_frame_manifest(out, fps=2.0, frame_rows=rows)
    content = out.read_text(encoding="utf-8")
    assert '"frame_count": 1' in content
    assert '"fps": 2.0' in content
