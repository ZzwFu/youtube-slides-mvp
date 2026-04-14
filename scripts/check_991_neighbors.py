"""Check FSM metrics for frame_000991 and its neighbors."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from youtube_slides_mvp.dedupe import _directional_change, _dark_cover
from youtube_slides_mvp.frame_cache import FrameCache

RUNS_DIR = Path(__file__).parent.parent / "runs"
run_name = sys.argv[1] if len(sys.argv) > 1 else "slide-v3-full-progressive"
src_run = RUNS_DIR / run_name
frames_raw_dir = src_run / "frames_raw"

fc = FrameCache()

def metrics(a_path, b_path):
    a = fc.get(a_path)
    b = fc.get(b_path)
    diff = float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)
    dc, da = _directional_change(a, b)
    dark_a, dark_b = _dark_cover(a, b)
    delta = b.astype(np.float32) - a.astype(np.float32)
    neg = float(np.mean(np.clip(-delta, 0, None)) / 255.0)
    return {"diff": diff, "dir_neg": neg, "dc": dc, "da": da, "dark_a": dark_a, "dark_b": dark_b}

pairs = [
    ("frame_000948.jpg", "frame_000991.jpg"),
    ("frame_000991.jpg", "frame_001024.jpg"),
    ("frame_000948.jpg", "frame_001024.jpg"),
]

for a_name, b_name in pairs:
    a_path = frames_raw_dir / a_name
    b_path = frames_raw_dir / b_name
    if not a_path.exists() or not b_path.exists():
        print(f"{a_name} → {b_name}: MISSING")
        continue
    m = metrics(a_path, b_path)
    print(f"{a_name} → {b_name}:")
    print(f"  diff={m['diff']:.4f}  dir_neg={m['dir_neg']:.5f}  dc={m['dc']:.4f}  da={m['da']:.4f}  dark_b={m['dark_b']:.4f}")
    
    # Check Tier A: diff≤0.10, neg≤0.02, dc≥0.60, da≤0.35
    tier_a = m['diff'] <= 0.10 and m['dir_neg'] <= 0.02 and m['dc'] >= 0.60 and m['da'] <= 0.35
    # Check Tier B: neg≤0.005, dc≥0.90, da≤0.10  
    tier_b = m['dir_neg'] <= 0.005 and m['dc'] >= 0.90 and m['da'] <= 0.10
    # Post-refill FSM: diff≤0.03, neg≤0.007, dc≥0.90, da≤0.05
    post = m['diff'] <= 0.03 and m['dir_neg'] <= 0.007 and m['dc'] >= 0.90 and m['da'] <= 0.05
    
    print(f"  Tier A: {tier_a}  Tier B: {tier_b}  Post-refill: {post}")
