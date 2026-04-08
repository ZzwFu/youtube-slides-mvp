from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.dedupe import DedupeConfig, dedupe_frames


def _save(path: Path, value: int) -> None:
    arr = np.full((144, 256), value, dtype=np.uint8)
    Image.fromarray(arr).save(path, format="JPEG")


def test_dedupe_collapses_near_duplicates(tmp_path: Path) -> None:
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"
    f3 = tmp_path / "frame_000003.jpg"
    _save(f1, 120)
    _save(f2, 121)
    _save(f3, 240)

    selected, stats = dedupe_frames([f1, f2, f3], DedupeConfig())
    assert len(selected) == 2
    assert stats["input"] == 3
    assert "after_e" in stats
    assert "after_f" in stats


def test_stage_f_keeps_balanced_replacement(tmp_path: Path) -> None:
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"
    f3 = tmp_path / "frame_000003.jpg"

    base = np.full((144, 256), 235, dtype=np.uint8)

    # Frame 1: left text block.
    a1 = base.copy()
    a1[20:40, 20:100] = 40

    # Frame 2: progressive reveal (same area becomes denser).
    a2 = a1.copy()
    a2[40:52, 20:100] = 55

    # Frame 3: replacement style change (old text removed, new text elsewhere).
    a3 = base.copy()
    a3[20:40, 140:220] = 40
    a3[40:52, 140:220] = 55

    Image.fromarray(a1).save(f1, format="JPEG")
    Image.fromarray(a2).save(f2, format="JPEG")
    Image.fromarray(a3).save(f3, format="JPEG")

    selected, _ = dedupe_frames([f1, f2, f3], DedupeConfig())

    # Expected: progressive pair collapses to frame2, replacement frame3 is kept.
    assert [p.name for p in selected] == ["frame_000002.jpg", "frame_000003.jpg"]
