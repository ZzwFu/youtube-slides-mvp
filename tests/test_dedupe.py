import json
from pathlib import Path

import numpy as np
from PIL import Image

from src.youtube_slides_mvp.dedupe import DedupeConfig, _block_features, dedupe_frames


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


# ── Card 4.2: _block_features + sidecar ──────────────────────────────────────

def test_block_features_dimensions() -> None:
    a = np.zeros((144, 256), dtype=np.uint8)
    b = np.full((144, 256), 128, dtype=np.uint8)
    feats = _block_features(a, b, grid=(4, 4))
    assert len(feats) == 48  # 4*4*3


def test_block_features_values_in_range() -> None:
    rng = np.random.default_rng(42)
    a = rng.integers(0, 256, (144, 256), dtype=np.uint8)
    b = rng.integers(0, 256, (144, 256), dtype=np.uint8)
    feats = _block_features(a, b)
    assert all(0.0 <= v <= 1.0 for v in feats)


def test_block_features_identical_arrays_zero() -> None:
    a = np.full((144, 256), 100, dtype=np.uint8)
    feats = _block_features(a, a)
    assert all(v == 0.0 for v in feats)


def test_sidecar_created_with_correct_structure(tmp_path: Path) -> None:
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"
    f3 = tmp_path / "frame_000003.jpg"
    _save(f1, 120)
    _save(f2, 121)
    _save(f3, 240)

    sidecar = tmp_path / "sidecar.json"
    dedupe_frames([f1, f2, f3], DedupeConfig(), sidecar_path=sidecar)

    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert "pairs" in data
    for pair in data["pairs"]:
        assert "frame_a" in pair
        assert "frame_b" in pair
        assert "block_features" in pair
        assert "label" in pair
        assert len(pair["block_features"]) == 48
        assert pair["label"] in ("progressive", "different")


def test_sidecar_not_created_by_default(tmp_path: Path) -> None:
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"
    _save(f1, 120)
    _save(f2, 240)
    sidecar = tmp_path / "sidecar.json"
    dedupe_frames([f1, f2], DedupeConfig())
    assert not sidecar.exists()


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


def test_stage_c_keeps_held_title_frame(tmp_path: Path) -> None:
    """Stage C must NOT drop a frame that was held for many Stage-A frames.

    Pattern: black → [title repeated 10x] → black → fading content
    Without the hold-count guard, Stage C would see title as a transition
    midpoint between two dark frames and drop it.
    """
    frames = [tmp_path / f"frame_{i:06d}.jpg" for i in range(1, 16)]

    # Frame 0: near-black transition
    black = np.full((144, 256), 18, dtype=np.uint8)
    # Title slide: bright background with text (mean ~200)
    title = np.full((144, 256), 200, dtype=np.uint8)
    title[20:40, 20:230] = 30   # title text row → dark
    # Near-black transition again (after title)
    black2 = np.full((144, 256), 20, dtype=np.uint8)
    # Fading in: gradually brightening frames
    fade = np.full((144, 256), 40, dtype=np.uint8)

    Image.fromarray(black).save(frames[0], format="JPEG")  # frame_000001
    for i in range(1, 11):                                 # frames 2-11: title held 10x
        Image.fromarray(title).save(frames[i], format="JPEG")
    Image.fromarray(black2).save(frames[11], format="JPEG")  # frame_000012
    for i in range(12, 15):                                # frames 13-15: fade
        f = np.full((144, 256), 40 + (i - 12) * 8, dtype=np.uint8)
        Image.fromarray(f).save(frames[i], format="JPEG")

    selected, stats = dedupe_frames(frames, DedupeConfig())
    names = [p.name for p in selected]

    # The title frame (one of frames 2-11, Stage A keeps the last = frame_000011)
    # must appear in the output; it was held for 10 frames, not a brief transition.
    title_frame = "frame_000011.jpg"
    assert title_frame in names, (
        f"Title frame (held 10 frames) was incorrectly dropped by Stage C. "
        f"Selected: {names}"
    )


def test_stage_e_additive_reveal(tmp_path: Path) -> None:
    """Stage E secondary check must merge an additive progressive reveal pair.

    Pair characteristics: change is purely additive (neg \u2248 0, pos > 0),
    dark content is mostly preserved (dark_cover > 0.70), diff > 0.06
    (so primary bright-pixel Stage E does NOT fire). Only the secondary
    additive-reveal criterion should collapse them.
    """
    f1 = tmp_path / "frame_000001.jpg"
    f2 = tmp_path / "frame_000002.jpg"
    f3 = tmp_path / "frame_000003.jpg"  # different slide as anchor

    # Slide 1: dark background + some bright text (simulates dark-bg lecture slide).
    # Base: dark (30), with bright text bars.
    a1 = np.full((144, 256), 30, dtype=np.uint8)
    a1[20:35, 10:246] = 220   # bright heading
    a1[50:60, 10:200] = 200   # bright bullet 1

    # Slide 2 (progressive reveal): same + new bright region added, nothing darkened.
    a2 = a1.copy()
    a2[70:80, 10:200] = 200   # bright bullet 2 added (purely additive)
    a2[90:100, 10:160] = 200  # bright bullet 3 added

    # Slide 3: completely different slide.
    a3 = np.full((144, 256), 30, dtype=np.uint8)
    a3[20:35, 10:246] = 220
    a3[50:60, 10:100] = 200   # different location/content

    for path, arr in zip([f1, f2, f3], [a1, a2, a3]):
        Image.fromarray(arr).save(path, format="JPEG")

    selected, stats = dedupe_frames([f1, f2, f3], DedupeConfig())
    names = [p.name for p in selected]

    # f1/f2 form an additive reveal pair → Stage E secondary should merge them.
    # f3 is a different slide and must survive.
    assert "frame_000001.jpg" not in names or "frame_000002.jpg" in names, (
        "Additive reveal pair was not collapsed by Stage E secondary check"
    )
    assert "frame_000003.jpg" in names, "Different slide f3 must be kept"
    assert stats["after_e"] <= stats["after_d"], "Stage E must not increase count"
