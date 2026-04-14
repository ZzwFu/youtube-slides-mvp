"""Trace which pipeline stage introduces the problem frames."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.dedupe import DedupeConfig, dedupe_frames
import youtube_slides_mvp.cli as _cli

RUNS_DIR = Path(__file__).parent.parent / "runs"

def check_frames(label, selected_orig, targets):
    names = {p.name for p in selected_orig}
    present = [t for t in targets if t in names]
    absent = [t for t in targets if t not in names]
    print(f"  [{label}] total={len(selected_orig)} present={present} absent={absent}")

def main():
    src_run = RUNS_DIR / (sys.argv[1] if len(sys.argv) > 1 else "slide-v2-full-progressive")
    frames_raw_dir = src_run / "frames_raw"
    norms_dir = src_run / "frames_norm"
    manifest = json.loads((src_run / "artifacts" / "frame_manifest.json").read_text())
    frame_rows = list(manifest.get("frames", []))

    targets = ["frame_000698.jpg", "frame_000702.jpg", "frame_000802.jpg",
               "frame_000991.jpg", "frame_001676.jpg", "frame_001691.jpg"]
    
    norm_paths = sorted(norms_dir.glob("*.jpg"))
    print(f"Loaded: {len(norm_paths)} preprocessed frames")

    # D4/D5: Dedupe
    selected_norm, dedupe_stats = dedupe_frames(norm_paths, DedupeConfig())
    selected_orig = [frames_raw_dir / p.name for p in selected_norm]
    selected_rows = _cli._rows_for_selected(selected_orig, frame_rows)
    check_frames("After dedupe", selected_orig, targets)

    # Novelty refill
    selected_orig, selected_rows, novelty_count = _cli._refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=frames_raw_dir,
        strategy="novelty",
        min_gap_sec=15.0,
        max_rounds=3,
    )
    check_frames("After novelty refill", selected_orig, targets)
    print(f"  novelty rescued: {novelty_count}")

    # _complete_pages (Phase 1 + Phase 2 FSM)
    selected_orig, selected_rows, completed, fsm_collapsed, dropped = _cli._complete_pages(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=frames_raw_dir,
        mode="iterative",
    )
    check_frames("After complete+FSM", selected_orig, targets)
    print(f"  completed={completed} fsm_collapsed={fsm_collapsed} dropped={dropped}")

    # Show timestamps around problem areas after FSM
    for p, r in zip(selected_orig, selected_rows):
        t = float(r.get("timestamp_sec", 0))
        if 690 <= t <= 725 or 795 <= t <= 825:
            print(f"    post-FSM: {p.name} t={t:.1f}s")

    # Confidence refill (fsm_group)
    selected_orig, selected_rows, conf_count = _cli._refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=frames_raw_dir,
        strategy="fsm_group",
        min_gap_sec=15.0,
        max_rounds=2,
    )
    check_frames("After confidence refill", selected_orig, targets)
    print(f"  confidence rescued: {conf_count}")

    # Post-refill FSM collapse (with logging)
    from youtube_slides_mvp.dedupe import _directional_change, _dark_cover
    fc2 = _cli.FrameCache()
    pre_fsm = list(zip(selected_orig, selected_rows))
    pre_fsm.sort(key=lambda it: float(it[1].get("timestamp_sec", 0)))
    for idx in range(len(pre_fsm) - 1):
        cp, cr = pre_fsm[idx]
        np_, nr = pre_fsm[idx+1]
        ca = fc2.get(cp)
        na = fc2.get(np_)
        import numpy as np_lib
        d = float(np_lib.mean(np_lib.abs(ca.astype(np_lib.float32) - na.astype(np_lib.float32))) / 255.0)
        neg, pos = _directional_change(ca, na)
        dc, da = _dark_cover(ca, na)
        tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
        tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
        if tier_a or tier_b:
            t1 = float(cr.get("timestamp_sec", 0))
            t2 = float(nr.get("timestamp_sec", 0))
            tier = "A" if tier_a else "B"
            print(f"    COLLAPSE({tier}): {cp.name}(t={t1:.0f}) → {np_.name}(t={t2:.0f})  d={d:.4f} neg={neg:.4f} dc={dc:.4f} da={da:.4f}")
    
    selected_orig, selected_rows, post_fsm = _cli._fsm_collapse(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        fsm_max_diff=0.03,
        fsm_max_neg=0.007,
        fsm_min_dark_cover=0.90,
        fsm_max_dark_add=0.05,
        enable_tier_b=False,
    )
    check_frames("After post-refill FSM", selected_orig, targets)
    print(f"  post-refill FSM collapsed: {post_fsm}")

    # Cleanup
    selected_orig, selected_rows, merged = _cli._cleanup_close_pairs(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
    )
    check_frames("After cleanup", selected_orig, targets)
    print(f"  merged: {merged}")

    print(f"\nFinal page count: {len(selected_orig)}")

if __name__ == "__main__":
    main()
