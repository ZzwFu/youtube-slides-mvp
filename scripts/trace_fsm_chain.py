"""Trace the exact Phase 2 FSM chain around frame_000991 after Phase 1 completion."""
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

# Reproduce pipeline up to Phase 1 output
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

# Phase 0: drop blank
pre_orig = []
pre_rows = []
for p, r in zip(selected_orig, selected_rows):
    if not _cli._is_blank_transition_frame(p):
        pre_orig.append(p)
        pre_rows.append(dict(r))

# Phase 1: completion (manual reproduction)
fc = FrameCache()
base_orig = list(pre_orig)
base_rows = [dict(r) for r in pre_rows]
out_orig = list(pre_orig)
out_rows = [dict(r) for r in pre_rows]

for i, (page_path, page_row) in enumerate(zip(base_orig, base_rows)):
    t_base = float(page_row.get("timestamp_sec", 0.0))
    if i + 1 < len(base_rows):
        t_next = float(base_rows[i + 1].get("timestamp_sec", t_base + 60))
        t_limit = min(t_base + 30.0, (t_base + t_next) / 2)
    else:
        t_limit = t_base + 30.0
    if t_limit <= t_base + 1.0:
        continue
    
    current_path = page_path
    current_row = dict(page_row)
    changed = False
    local_used = {current_path.name}
    
    while True:
        t_current = float(current_row.get("timestamp_sec", 0.0))
        a_page = fc.get(current_path)
        candidates = [r for r in frame_rows
                      if t_current + 1.0 < float(r.get("timestamp_sec", 0.0)) <= t_limit]
        if not candidates:
            break
        
        best_path = None
        best_diff = -1.0
        best_row = None
        for row in candidates:
            cname = str(row.get("frame_name", ""))
            if not cname or cname in local_used:
                continue
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
                best_row = dict(row)
        
        if best_path is None:
            break
        current_path = best_path
        current_row = best_row
        local_used.add(current_path.name)
        changed = True
    
    if changed:
        t_old = float(page_row.get("timestamp_sec", 0))
        t_new = float(current_row.get("timestamp_sec", 0))
        if 940 <= t_old <= 1040 or 940 <= t_new <= 1040:
            print(f"Phase 1 COMPLETED [{i}]: {page_path.name}(t={t_old:.0f}) → {current_path.name}(t={t_new:.0f})")
        out_orig[i] = current_path
        out_rows[i] = current_row

# Now show the sorted post-Phase-1 frames around t=990
print("\n--- Post-Phase-1 frames around t=940-1040 ---")
valid = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0)))
for j, (p, r) in enumerate(valid):
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  [{j}] {p.name} t={t:.0f}s")

# Now simulate Phase 2 FSM for this section
print("\n--- Phase 2 FSM walk around t=940-1040 ---")
# Find the range
start_j = None
for j, (p, r) in enumerate(valid):
    t = float(r.get("timestamp_sec", 0))
    if t >= 890 and start_j is None:
        start_j = max(0, j)
    if t > 1050:
        end_j = j
        break
else:
    end_j = len(valid)

# Simulate FSM from start_j
cand_p, cand_r = valid[start_j]
cand_a = fc.get(cand_p)
t_c = float(cand_r.get("timestamp_sec", 0))
print(f"  Start cand: {cand_p.name}(t={t_c:.0f})")

for j in range(start_j + 1, min(end_j + 2, len(valid))):
    cur_p, cur_r = valid[j]
    cur_a = fc.get(cur_p)
    t_cur = float(cur_r.get("timestamp_sec", 0))
    
    d = float(np.mean(np.abs(cand_a.astype(np.float32) - cur_a.astype(np.float32))) / 255.0)
    neg, _ = _directional_change(cand_a, cur_a)
    dc, da = _dark_cover(cand_a, cur_a)
    tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
    tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
    additive = tier_a or tier_b
    
    action = "COLLAPSE" if additive else "EMIT cand"
    tier = "A" if tier_a else ("B" if tier_b else "-")
    print(f"  {cand_p.name}(t={t_c:.0f}) → {cur_p.name}(t={t_cur:.0f}): d={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f} Tier={tier} → {action}")
    
    if additive:
        cand_p, cand_r, cand_a = cur_p, cur_r, cur_a
        t_c = t_cur
    else:
        print(f"    EMIT: {cand_p.name}(t={t_c:.0f})")
        cand_p, cand_r, cand_a = cur_p, cur_r, cur_a
        t_c = t_cur

print(f"    EMIT (final): {cand_p.name}(t={t_c:.0f})")
