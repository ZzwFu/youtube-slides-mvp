"""Compute spatial change distribution for FSM pairs.
Compare block-level change patterns for genuine progressive pairs vs the problem pair 948→991."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from youtube_slides_mvp.dedupe import _block_features, _directional_change, _dark_cover
from youtube_slides_mvp.frame_cache import FrameCache

RUNS_DIR = Path(__file__).parent.parent / "runs"
run_name = sys.argv[1] if len(sys.argv) > 1 else "slide-v3-full-progressive"
src_run = RUNS_DIR / run_name
frames_raw_dir = src_run / "frames_raw"
fc = FrameCache()

def metrics(a_name, b_name):
    a = fc.get(frames_raw_dir / a_name)
    b = fc.get(frames_raw_dir / b_name)
    diff = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)
    neg, pos = _directional_change(a, b)
    dc, da = _dark_cover(a, b)
    
    # Block features: 48 values = 16 blocks × (mean_diff, mean_neg, mean_pos)
    feats = _block_features(a, b)
    block_diffs = feats[0::3]  # 16 mean abs diff values
    
    # Change spread: fraction of blocks with significant change
    for block_th in [0.02, 0.03, 0.04, 0.05]:
        active = sum(1 for d in block_diffs if d > block_th)
        spread = active / len(block_diffs)
        if block_th == 0.03:
            spread_03 = spread
    
    # Also compute std of block diffs (low std = uniform change, high std = localized)
    block_std = float(np.std(block_diffs))
    block_max = max(block_diffs)
    block_min = min(block_diffs)
    
    return {
        "diff": diff, "neg": neg, "dc": dc, "da": da,
        "block_diffs": block_diffs,
        "spread_03": spread_03,
        "block_std": block_std, "block_max": block_max,
    }

# Problem pair (should NOT collapse — different slides)
print("=== PROBLEM PAIRS (should NOT collapse) ===")
problem_pairs = [
    ("frame_000948.jpg", "frame_000991.jpg", "948→991 (slide change, 43s)"),
]

for a, b, label in problem_pairs:
    m = metrics(a, b)
    tier_a = m["diff"] <= 0.10 and m["neg"] <= 0.02 and m["dc"] >= 0.60 and m["da"] <= 0.35
    print(f"\n{label}:")
    print(f"  diff={m['diff']:.4f} neg={m['neg']:.5f} dc={m['dc']:.4f} da={m['da']:.4f} TierA={tier_a}")
    print(f"  spread@0.03={m['spread_03']:.3f} block_std={m['block_std']:.4f} block_max={m['block_max']:.4f}")
    diffs_str = " ".join(f"{d:.3f}" for d in m['block_diffs'])
    print(f"  blocks: [{diffs_str}]")

# Genuine progressive pairs (SHOULD collapse)
print("\n=== GENUINE PROGRESSIVE PAIRS (should collapse) ===")
genuine_pairs = [
    ("frame_000991.jpg", "frame_001005.jpg", "991→1005 (reveal, 14s)"),
    ("frame_001005.jpg", "frame_001024.jpg", "1005→1024 (reveal, 19s)"),
    ("frame_001065.jpg", "frame_001110.jpg", "1065→1110 (reveal, 45s)"),
    ("frame_001124.jpg", "frame_001132.jpg", "1124→1132 (reveal, 8s)"),
    ("frame_001170.jpg", "frame_001185.jpg", "1170→1185 (reveal, 15s)"),
    ("frame_001448.jpg", "frame_001455.jpg", "1448→1455 (reveal, 7s)"),
    ("frame_001809.jpg", "frame_001830.jpg", "1809→1830 (reveal, 21s)"),
]

for a, b, label in genuine_pairs:
    ap = frames_raw_dir / a
    bp = frames_raw_dir / b
    if not ap.exists() or not bp.exists():
        print(f"\n{label}: MISSING")
        continue
    m = metrics(a, b)
    tier_a = m["diff"] <= 0.10 and m["neg"] <= 0.02 and m["dc"] >= 0.60 and m["da"] <= 0.35
    print(f"\n{label}:")
    print(f"  diff={m['diff']:.4f} neg={m['neg']:.5f} dc={m['dc']:.4f} da={m['da']:.4f} TierA={tier_a}")
    print(f"  spread@0.03={m['spread_03']:.3f} block_std={m['block_std']:.4f} block_max={m['block_max']:.4f}")
    diffs_str = " ".join(f"{d:.3f}" for d in m['block_diffs'])
    print(f"  blocks: [{diffs_str}]")

# Also check non-additive pairs that correctly DON'T collapse
print("\n=== NON-ADDITIVE PAIRS (correctly rejected) ===")
nonadd_pairs = [
    ("frame_000900.jpg", "frame_000948.jpg", "900→948 (different slide, 48s)"),
    ("frame_001024.jpg", "frame_001031.jpg", "1024→1031 (different slide, 7s)"),
]

for a, b, label in nonadd_pairs:
    ap = frames_raw_dir / a
    bp = frames_raw_dir / b
    if not ap.exists() or not bp.exists():
        print(f"\n{label}: MISSING")
        continue
    m = metrics(a, b)
    tier_a = m["diff"] <= 0.10 and m["neg"] <= 0.02 and m["dc"] >= 0.60 and m["da"] <= 0.35
    print(f"\n{label}:")
    print(f"  diff={m['diff']:.4f} neg={m['neg']:.5f} dc={m['dc']:.4f} da={m['da']:.4f} TierA={tier_a}")
    print(f"  spread@0.03={m['spread_03']:.3f} block_std={m['block_std']:.4f} block_max={m['block_max']:.4f}")
    diffs_str = " ".join(f"{d:.3f}" for d in m['block_diffs'])
    print(f"  blocks: [{diffs_str}]")
