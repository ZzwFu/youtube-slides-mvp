"""Trace novelty refill for the 947-1023 gap specifically."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
from youtube_slides_mvp.dedupe import _directional_change, _dark_cover, dedupe_frames, DedupeConfig
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
print(f"After dedupe: {len(selected_orig)}")

# Novelty refill round 1 - trace the gap at 947-1023
def _diff(a, b):
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)

fc = FrameCache()
by_ts = sorted(frame_rows, key=lambda r: float(r.get("timestamp_sec", 0)))
selected_set = {p.name for p in selected_orig}

# Find the gap around t=947
print(f"\nTimestamps around 900-1100s:")
for i in range(len(selected_rows)):
    t = float(selected_rows[i].get("timestamp_sec", 0))
    if 900 <= t <= 1100:
        print(f"  [{i}] {selected_orig[i].name} t={t:.0f}s")

for i in range(len(selected_rows) - 1):
    t_a = float(selected_rows[i].get("timestamp_sec", 0))
    t_b = float(selected_rows[i + 1].get("timestamp_sec", 0))
    if 900 < t_a < 1000 and t_b - t_a > 30:
        print(f"\nGap [{i}]: {selected_orig[i].name}(t={t_a:.0f}) → {selected_orig[i+1].name}(t={t_b:.0f}) dt={t_b-t_a:.0f}s")
        
        p_a = selected_orig[i]
        p_b = selected_orig[i + 1]
        a_left = fc.get(p_a)
        a_right = fc.get(p_b)
        
        candidates = []
        for row in by_ts:
            t = float(row.get("timestamp_sec", 0))
            if t <= t_a + 1.0 or t >= t_b - 1.0:
                continue
            name = str(row.get("frame_name", ""))
            if not name or name in selected_set:
                continue
            cpath = frames_raw_dir / name
            if not cpath.exists():
                continue
            candidates.append((cpath, dict(row)))
        
        print(f"  Candidates in gap: {len(candidates)}")
        
        # Sample like the algorithm does
        sample_size = 20
        step = max(1, len(candidates) // sample_size)
        sampled = candidates[::step]
        print(f"  Sampled: {len(sampled)} (step={step})")
        
        # Check if 991 is in sampled
        sampled_names = [c[0].name for c in sampled]
        has_991 = "frame_000991.jpg" in sampled_names
        print(f"  frame_000991 in sampled: {has_991}")
        if not has_991:
            # Check where 991 would be
            for j, (cp, row) in enumerate(candidates):
                if cp.name == "frame_000991.jpg":
                    print(f"    frame_000991 is at candidate index {j} (sample step={step}, would need index {j} % {step} == 0: {j % step == 0})")
                    break
        
        # Find what novelty picks
        best_score = -1.0
        best_path = None
        novelty_th = 0.075
        for cp, row in sampled:
            arr = fc.get(cp)
            score = min(_diff(arr, a_left), _diff(arr, a_right))
            if cp.name == "frame_000991.jpg":
                print(f"  frame_000991 novelty score: {score:.4f} (th={novelty_th}) {'PASS' if score >= novelty_th else 'FAIL'}")
                print(f"    diff_left={_diff(arr, a_left):.4f} diff_right={_diff(arr, a_right):.4f}")
            if score > best_score:
                best_score = score
                best_path = cp
        
        if best_path:
            print(f"  Best candidate: {best_path.name} score={best_score:.4f}")
        break
