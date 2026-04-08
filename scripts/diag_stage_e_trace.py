"""
Deep trace of Stage E for the problematic pairs.
Simulate dedupe_frames on just the frames involved in these pairs.
"""
import sys, json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import (
    _load_gray, _diff, _reveal, _motion_ratio, _hash_bits, _hamming,
    _directional_change, _dark_cover, _sorted_unique, DedupeConfig
)

RUN    = Path(__file__).parent.parent / "runs/slide-20260408-054947"
NORM   = RUN / "frames_norm"

# Load the actual normalized frames for these pages
slides = json.loads((RUN / "artifacts/slides.json").read_text())["slides"]
by_page = {r["page"]: r for r in slides}

# Collect frame paths for pages 6-10 (includes p08 and p09)
page_range = list(range(6, 11))
frame_map = {}
for pg in page_range:
    r = by_page[pg]
    frame_map[pg] = NORM / r["frame_name"]

frame_paths = [frame_map[pg] for pg in page_range]
arrays  = [_load_gray(p) for p in frame_paths]
hashes  = [_hash_bits(a) for a in arrays]
cfg = DedupeConfig()

print("=== Stage E trace for pages 6-10 (focuses on p08/p09) ===")
print(f"Frames: {[p.name for p in frame_paths]}")
print(f"Config: progressive_lookback={cfg.progressive_lookback}")

# Simulate Stage D output (assume all frames come through D unchanged, since p08/p09 are sequential)
out_idx = list(range(len(arrays)))  # [0,1,2,3,4] → [p6, p7, p8, p9, p10]

# Now simulate Stage E
e_idx = []
for i, idx_i in enumerate(out_idx):
    print(f"\n--- Processing out_idx[{i}] = frame index {idx_i} (p{page_range[i]}) ---")
    merged = False
    
    for back in range(len(e_idx) - 1, max(-1, len(e_idx) - 1 - cfg.progressive_lookback), -1):
        j = e_idx[back]
        idx_j = j  # In this simulation, e_idx contains original indices directly
        
        d = _diff(arrays[idx_j], arrays[idx_i])
        hd = _hamming(hashes[idx_j], hashes[idx_i])
        cover, add = _reveal(arrays[idx_j], arrays[idx_i])
        neg, pos = _directional_change(arrays[idx_j], arrays[idx_i])
        dc, da = _dark_cover(arrays[idx_j], arrays[idx_i])
        
        primary = (
            d <= cfg.progressive_diff_th
            and hd <= cfg.progressive_hash_th
            and cover >= cfg.progressive_cover_th
            and add <= cfg.progressive_add_th
        )
        secondary = (
            d <= cfg.additive_reveal_diff_th
            and neg <= cfg.additive_neg_max
            and dc >= cfg.additive_dark_cover_th
            and da <= cfg.additive_dark_add_th
        ) if not primary else False
        
        page_j = page_range[idx_j]
        match = "PRIMARY" if primary else ("SECONDARY" if secondary else "NO MATCH")
        print(f"  vs e_idx[{back}]={idx_j} (p{page_j}): "
              f"d={d:.5f} hd={hd:3d} cov={cover:.3f} add={add:.3f} "
              f"neg={neg:.5f} dc={dc:.3f} da={da:.3f} → {match}")
        
        if primary or secondary:
            e_idx[back] = idx_i
            merged = True
            print(f"    ✓ MERGED! e_idx[{back}] := {idx_i}")
            break
    
    if not merged:
        e_idx.append(idx_i)
        print(f"  NO MATCH → e_idx.append({idx_i}) → e_idx={e_idx}")

e_idx = _sorted_unique(e_idx)
print(f"\nAfter _sorted_unique: e_idx={e_idx}")
print(f"Final pages: {[page_range[i] for i in e_idx]}")
print(f"\nExpected: P08 and P09 should be merged (p08 → p09)")
print(f"Actual  : {f'✓ MERGED' if 0 not in e_idx or 0 not in e_idx else '✗ NOT MERGED'}")
