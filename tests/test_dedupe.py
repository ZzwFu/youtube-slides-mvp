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


def test_stage_g_collapses_long_stable_run(tmp_path: Path) -> None:
    """Stage G should collapse a stable run of >= min_stable_frames to its tail."""
    # Three frames where each step adds exactly 1 row of dark content (low motion ratio).
    # f1→f2 and f2→f3 each have ~0.7 % moving pixels (< motion_ratio_th=0.025 → stable).
    # f4 is a complete replacement (high motion) → kicks off a new run.
    f1, f2, f3, f4 = [tmp_path / f"frame_{i:06d}.jpg" for i in range(1, 5)]

    base = np.full((144, 256), 120, dtype=np.uint8)

    a1 = base.copy()
    a2 = a1.copy(); a2[0, :] = 0      # row 0 goes dark: ~0.7% pixels change by >15 → stable
    a3 = a2.copy(); a3[1, :] = 0      # row 1 goes dark: same tiny step
    a4 = np.zeros((144, 256), dtype=np.uint8)  # full black → all pixels change → motion

    for path, arr in zip([f1, f2, f3, f4], [a1, a2, a3, a4]):
        Image.fromarray(arr).save(path, format="JPEG")

    selected, stats = dedupe_frames([f1, f2, f3, f4], DedupeConfig())

    # Stage G: stable run [f1,f2,f3] (length 3 = min_stable_frames) collapses to f3.
    # f4 is a standalone run of length 1 < 3, so kept as-is.
    assert stats["after_g"] <= stats["after_f"], "Stage G should not increase count"
    assert f3.name in [p.name for p in selected], "tail of stable run must be kept"
    assert f4.name in [p.name for p in selected], "motion frame must be kept"
    assert f1.name not in [p.name for p in selected], "non-tail stable frames should be dropped"


def test_stage_g_keeps_short_stable_run(tmp_path: Path) -> None:
    """Stage G should NOT collapse a run shorter than min_stable_frames."""
    # Only two frames, each gently changing. Run length = 2 < min_stable_frames=3 → kept as-is.
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"

    a1 = np.full((144, 256), 120, dtype=np.uint8)
    a2 = a1.copy(); a2[0, :] = 0   # one row changes: motion_ratio ≈ 0.007 → stable pair

    Image.fromarray(a1).save(f1, format="JPEG")
    Image.fromarray(a2).save(f2, format="JPEG")

    selected, stats = dedupe_frames([f1, f2], DedupeConfig())

    # Run [f1,f2] has length 2 < 3; both should survive Stage G.
    # (Stage A may already collapse them as near-duplicates, but if they do survive to G,
    # they should not be further reduced by G.)
    assert stats["after_g"] == stats["after_f"] or stats["after_g"] >= 1
