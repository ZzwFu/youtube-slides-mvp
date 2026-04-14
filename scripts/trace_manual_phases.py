"""Manually reproduce _complete_pages phases to trace frame_000991."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from youtube_slides_mvp.dedupe import dedupe_frames, DedupeConfig, _directional_change, _dark_cover
from youtube_slides_mvp.frame_cache import FrameCache
from youtube_slides_mvp.text_compare import compare_text_prefix
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
)
print(f"After novelty: {len(selected_orig)} (rescued={rescued})")

# Phase 0: blank drop
pre_orig = []
pre_rows = []
dropped = 0
for p, r in zip(selected_orig, selected_rows):
    if _cli._is_blank_transition_frame(p):
        dropped += 1
    else:
        pre_orig.append(p)
        pre_rows.append(dict(r))
print(f"After blank drop: {len(pre_orig)} (dropped={dropped})")

# Check 991
idx_991 = None
for i, p in enumerate(pre_orig):
    if p.name == "frame_000991.jpg":
        idx_991 = i
        break
print(f"991 at position [{idx_991}]")

# Pre-completion FSM with detailed trace
fc = FrameCache()
valid = sorted(zip(pre_orig, pre_rows), key=lambda it: float(it[1].get("timestamp_sec", 0)))
fsm_out = []
collapsed = 0
if valid:
    cand_p, cand_r = valid[0]
    cand_a = fc.get(cand_p)
    for cur_p, cur_r in valid[1:]:
        cur_a = fc.get(cur_p)
        d = float(np.mean(np.abs(cand_a.astype(np.float32) - cur_a.astype(np.float32))) / 255.0)
        neg, _ = _directional_change(cand_a, cur_a)
        dc, da = _dark_cover(cand_a, cur_a)
        tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
        tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
        additive = tier_a or tier_b
        
        t_c = float(cand_r.get("timestamp_sec", 0))
        t_cur = float(cur_r.get("timestamp_sec", 0))
        
        is_991_involved = "991" in cand_p.name or "991" in cur_p.name
        is_near_991 = 940 <= t_c <= 1040 or 940 <= t_cur <= 1040
        
        if additive:
            if is_near_991 or is_991_involved:
                tier = "A" if tier_a else "B"
                print(f"  PRE-FSM COLLAPSE({tier}): {cand_p.name}(t={t_c:.0f}) → {cur_p.name}(t={t_cur:.0f}) d={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f}")
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a
            collapsed += 1
        else:
            if is_near_991 or is_991_involved:
                print(f"  PRE-FSM EMIT: {cand_p.name}(t={t_c:.0f}) [next: {cur_p.name}(t={t_cur:.0f}) d={d:.4f} neg={neg:.5f}]")
            fsm_out.append((cand_p, cand_r))
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a
    fsm_out.append((cand_p, cand_r))
print(f"After pre-FSM: {len(fsm_out)} (collapsed={collapsed})")

# Check if 991 is in fsm_out
has_991 = any(p.name == "frame_000991.jpg" for p, _ in fsm_out)
print(f"991 in pre-FSM output: {has_991}")

# Show frames around 991 in fsm_out
print("Pre-FSM output around t=940-1040:")
for p, r in fsm_out:
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  {p.name} t={t:.0f}s")

# Phase 2 (now): completion
base_orig = [p for p, _ in fsm_out]
base_rows = [dict(r) for _, r in fsm_out]
out_orig = list(base_orig)
out_rows = [dict(r) for r in base_rows]
completed = 0

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
        candidates = [r for r in frame_rows if t_current + 1.0 < float(r.get("timestamp_sec", 0.0)) <= t_limit]
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
            neg_, _ = _directional_change(a_page, arr)
            if neg_ > 0.012:
                continue
            dc_, _ = _dark_cover(a_page, arr)
            if dc_ < 0.75:
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
            print(f"COMPLETION [{i}]: {page_path.name}(t={t_old:.0f}) → {current_path.name}(t={t_new:.0f})")
        out_orig[i] = current_path
        out_rows[i] = current_row
        out_rows[i]["page"] = page_row.get("page", i+1)
        completed += 1

print(f"Completions: {completed}")

# Show post-completion frames around 991
print("Post-completion output around t=940-1040:")
for p, r in sorted(zip(out_orig, out_rows), key=lambda x: float(x[1].get("timestamp_sec", 0))):
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  {p.name} t={t:.0f}s")

# Post-completion FSM with trace
valid2 = sorted(zip(out_orig, out_rows), key=lambda it: float(it[1].get("timestamp_sec", 0)))
fsm2_out = []
collapsed2 = 0
if valid2:
    cand_p, cand_r = valid2[0]
    cand_a = fc.get(cand_p)
    for cur_p, cur_r in valid2[1:]:
        cur_a = fc.get(cur_p)
        d = float(np.mean(np.abs(cand_a.astype(np.float32) - cur_a.astype(np.float32))) / 255.0)
        neg, _ = _directional_change(cand_a, cur_a)
        dc, da = _dark_cover(cand_a, cur_a)
        tier_a = d <= 0.10 and neg <= 0.02 and dc >= 0.60 and da <= 0.35
        tier_b = neg <= 0.005 and dc >= 0.90 and da <= 0.10
        additive = tier_a or tier_b
        
        t_c = float(cand_r.get("timestamp_sec", 0))
        t_cur = float(cur_r.get("timestamp_sec", 0))
        is_near = 940 <= t_c <= 1040 or 940 <= t_cur <= 1040 or "991" in cand_p.name or "991" in cur_p.name
        
        if additive:
            if is_near:
                tier = "A" if tier_a else "B"
                print(f"  POST-FSM COLLAPSE({tier}): {cand_p.name}(t={t_c:.0f}) → {cur_p.name}(t={t_cur:.0f}) d={d:.4f} neg={neg:.5f} dc={dc:.4f} da={da:.4f}")
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a
            collapsed2 += 1
        else:
            if is_near:
                print(f"  POST-FSM EMIT: {cand_p.name}(t={t_c:.0f})")
            fsm2_out.append((cand_p, cand_r))
            cand_p, cand_r, cand_a = cur_p, dict(cur_r), cur_a
    fsm2_out.append((cand_p, cand_r))

print(f"After post-FSM: {len(fsm2_out)} (collapsed2={collapsed2})")
has_991_final = any(p.name == "frame_000991.jpg" for p, _ in fsm2_out)
print(f"991 in final output: {has_991_final}")
print("Final output around t=940-1040:")
for p, r in fsm2_out:
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  {p.name} t={t:.0f}s")
