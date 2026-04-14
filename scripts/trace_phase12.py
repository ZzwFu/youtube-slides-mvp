"""Trace Phase 1+2 for frame_000991 in _complete_pages."""
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

norm_paths = sorted(norms_dir.glob("*.jpg"))
selected_norm, _ = dedupe_frames(norm_paths, DedupeConfig())
selected_orig = [frames_raw_dir / p.name for p in selected_norm]
selected_rows = _cli._rows_for_selected(selected_orig, frame_rows)

selected_orig, selected_rows, rescued = _cli._refill_gaps(
    selected_orig=selected_orig,
    selected_rows=selected_rows,
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    strategy="novelty",
    min_gap_sec=15.0,
)
print(f"After novelty: {len(selected_orig)} (rescued={rescued})")

# Run _complete_pages to get the ACTUAL output
out_orig, out_rows, completed, fsm_collapsed, dropped = _cli._complete_pages(
    selected_orig=selected_orig,
    selected_rows=selected_rows,
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    mode="iterative",
)
print(f"After complete+FSM: {len(out_orig)} (completed={completed}, fsm_collapsed={fsm_collapsed}, dropped={dropped})")

# Check if 991 is in the output
has_991 = any(p.name == "frame_000991.jpg" for p in out_orig)
print(f"frame_000991 in output: {has_991}")

# Show what's around t=990 in the output
for i, (p, r) in enumerate(zip(out_orig, out_rows)):
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1030:
        print(f"  [{i}] {p.name} t={t:.0f}s")

# Now simulate Phase 0 + Phase 1 manually to see what happens to 991's neighbors
print("\n--- Manual trace of Phase 0 + Phase 1 ---")
pre_orig = []
pre_rows = []
dropped_b = 0
for p, r in zip(selected_orig, selected_rows):
    if _cli._is_blank_transition_frame(p):
        dropped_b += 1
    else:
        pre_orig.append(p)
        pre_rows.append(dict(r))

print(f"After Phase 0 (blank drop): {len(pre_orig)} (dropped={dropped_b})")

# Find 991 position after blank drop
idx_991 = None
for i, p in enumerate(pre_orig):
    if p.name == "frame_000991.jpg":
        idx_991 = i
        break

if idx_991 is not None:
    print(f"frame_000991 at position [{idx_991}]")
    # Show neighborhood
    for j in range(max(0, idx_991-2), min(len(pre_orig), idx_991+3)):
        t = float(pre_rows[j].get("timestamp_sec", 0))
        print(f"  [{j}] {pre_orig[j].name} t={t:.0f}s")

    # Phase 1: simulate completion for positions around 991
    fc = FrameCache()
    base_orig = list(pre_orig)
    base_rows = [dict(r) for r in pre_rows]
    
    print(f"\nPhase 1 completion for neighborhood of 991:")
    for check_idx in range(max(0, idx_991-2), min(len(base_orig), idx_991+3)):
        page_path = base_orig[check_idx]
        page_row = base_rows[check_idx]
        t_base = float(page_row.get("timestamp_sec", 0))
        
        if check_idx + 1 < len(base_rows):
            t_next = float(base_rows[check_idx + 1].get("timestamp_sec", t_base + 60))
            t_limit = min(t_base + 30.0, (t_base + t_next) / 2)
        else:
            t_limit = t_base + 30.0
        
        candidates = [
            r for r in frame_rows
            if t_base + 1.0 < float(r.get("timestamp_sec", 0.0)) <= t_limit
        ]
        
        # Find best completion
        a_page = fc.get(page_path)
        best_path = None
        best_name = ""
        best_diff = -1.0
        
        for row in candidates:
            cname = str(row.get("frame_name", ""))
            cpath = frames_raw_dir / cname
            if not cpath.exists() or _cli._is_blank_transition_frame(cpath):
                continue
            arr = fc.get(cpath)
            d = float(np.mean(np.abs(a_page.astype(np.float32) - arr.astype(np.float32))) / 255.0)
            if d < 0.008 or d > 0.15:
                continue
            neg, _ = _directional_change(a_page, arr)
            if neg > 0.012:
                continue
            dc, _ = _dark_cover(a_page, arr)
            if dc < 0.75:
                continue
            if d > best_diff:
                best_diff = d
                best_path = cpath
                best_name = cname
        
        if best_path:
            bt = [r for r in frame_rows if r.get("frame_name") == best_name]
            bt_t = float(bt[0].get("timestamp_sec", 0)) if bt else 0
            print(f"  [{check_idx}] {page_path.name}(t={t_base:.0f}) → COMPLETED to {best_name}(t={bt_t:.0f}) diff={best_diff:.4f} window=[{t_base+1:.0f},{t_limit:.0f}]")
        else:
            print(f"  [{check_idx}] {page_path.name}(t={t_base:.0f}) → no completion (candidates={len(candidates)}, t_limit={t_limit:.0f})")

# Now check Phase 2: what pairs would the FSM collapse around 991?
print(f"\n--- Phase 2 FSM pairs around t=990 ---")
# After Phase 1, the out_orig/out_rows has the actual completed frames
# Let me check pairs in the sorted result around where 991 would be
valid = sorted(zip(pre_orig, pre_rows), key=lambda it: float(it[1].get("timestamp_sec", 0)))
# Use the base completion info above - but actually need to run Phase 1 fully
# Let me just check the pre_orig pairs for 991 neighborhood
for j in range(max(0, idx_991-1), min(len(valid)-1, idx_991+2)):
    p_a, r_a = valid[j]
    p_b, r_b = valid[j+1]
    t_a = float(r_a.get("timestamp_sec", 0))
    t_b = float(r_b.get("timestamp_sec", 0))
    
    a_arr = fc.get(p_a)
    b_arr = fc.get(p_b)
    d = float(np.mean(np.abs(a_arr.astype(np.float32) - b_arr.astype(np.float32))) / 255.0)
    neg, _ = _directional_change(a_arr, b_arr)
    dc, da = _dark_cover(a_arr, b_arr)
    tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
    tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
    
    mark = " <<<COLLAPSE" if tier_a or tier_b else ""
    print(f"  {p_a.name}(t={t_a:.0f}) → {p_b.name}(t={t_b:.0f}): d={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f} A={tier_a} B={tier_b}{mark}")
