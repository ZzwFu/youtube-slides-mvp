"""Trace Phase 1 completion for frame_000991 position."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from youtube_slides_mvp.dedupe import dedupe_frames, DedupeConfig, _directional_change, _dark_cover
from youtube_slides_mvp.frame_cache import FrameCache
import youtube_slides_mvp.cli as _cli

RUNS_DIR = Path(__file__).parent.parent / "runs"
run_name = sys.argv[1] if len(sys.argv) > 1 else "slide-v3-full-progressive"
src_run = RUNS_DIR / run_name
frames_raw_dir = src_run / "frames_raw"
norms_dir = src_run / "frames_norm"
manifest = json.loads((src_run / "artifacts" / "frame_manifest.json").read_text())
frame_rows = list(manifest.get("frames", []))

# Reproduce dedupe
norm_paths = sorted(norms_dir.glob("*.jpg"))
selected_norm, _ = dedupe_frames(norm_paths, DedupeConfig())
selected_orig = [frames_raw_dir / p.name for p in selected_norm]
selected_rows = _cli._rows_for_selected(selected_orig, frame_rows)

# Run novelty refill (with min_gap_sec=15.0 to match pipeline fix)
selected_orig, selected_rows, rescued = _cli._refill_gaps(
    selected_orig=selected_orig,
    selected_rows=selected_rows,
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    strategy="novelty",
    min_gap_sec=15.0,
    ocr_texts=None,
)
print(f"After novelty: {len(selected_orig)} (rescued={rescued})")

# Find frame_000991 position
for i, p in enumerate(selected_orig):
    if p.name == "frame_000991.jpg":
        print(f"frame_000991 at position [{i}]")
        t_base = float(selected_rows[i].get("timestamp_sec", 0))
        t_next = float(selected_rows[i+1].get("timestamp_sec", 0)) if i+1 < len(selected_rows) else t_base + 60
        t_limit = min(t_base + 30.0, (t_base + t_next) / 2)
        print(f"  t_base={t_base:.0f} t_next={t_next:.0f} t_limit={t_limit:.1f}")
        print(f"  next frame: {selected_orig[i+1].name}" if i+1 < len(selected_orig) else "  (last)")
        break

# Now trace Phase 1 completion for this specific position
fc = FrameCache()
a_page = fc.get(selected_orig[i])
candidates = [
    r for r in frame_rows
    if t_base + 1.0 < float(r.get("timestamp_sec", 0.0)) <= t_limit
]
print(f"  Completion candidates: {len(candidates)}")

min_diff = 0.008
max_diff = 0.15
max_neg = 0.012
dark_cover_th = 0.75

best_path = None
best_diff = -1.0
best_name = ""
for row in candidates:
    cname = str(row.get("frame_name", ""))
    cpath = frames_raw_dir / cname
    if not cpath.exists() or _cli._is_blank_transition_frame(cpath):
        continue
    arr = fc.get(cpath)
    d = float(np.mean(np.abs(a_page.astype(np.float32) - arr.astype(np.float32))) / 255.0)
    neg, _pos = _directional_change(a_page, arr)
    dc, da = _dark_cover(a_page, arr)
    accepts = min_diff <= d <= max_diff and neg <= max_neg and dc >= dark_cover_th
    if d > 0.005:  # only print meaningful diffs
        if accepts or cname in ["frame_001020.jpg", "frame_001023.jpg", "frame_001006.jpg"]:
            print(f"    {cname}: diff={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f} accept={accepts}")
    if accepts and d > best_diff:
        best_diff = d
        best_path = cpath
        best_name = cname

if best_path:
    print(f"\n  COMPLETED to: {best_name} diff={best_diff:.4f}")
    # Now check: is completed frame additive with next?
    next_path = selected_orig[i + 1]
    completed_arr = fc.get(best_path)
    next_arr = fc.get(next_path)
    d = float(np.mean(np.abs(completed_arr.astype(np.float32) - next_arr.astype(np.float32))) / 255.0)
    neg, _pos = _directional_change(completed_arr, next_arr)
    dc, da = _dark_cover(completed_arr, next_arr)
    tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
    tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
    print(f"  {best_name} → {next_path.name}: diff={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f}")
    print(f"  Tier A: {tier_a}  Tier B: {tier_b}")
    if tier_a or tier_b:
        print("  >>> THIS CAUSES FSM COLLAPSE - frame_000991 slot gets dropped!")
else:
    print(f"\n  No completion found for frame_000991")
