"""
Check the relative positions of frame_000128 and frame_000149 in the Stage E processing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import _load_gray, _hash_bits, _hamming, _diff, _reveal, DedupeConfig

RUN  = Path(__file__).parent.parent / "runs/slide-20260408-054947"
NORM = RUN / "frames_norm"

norm_paths = sorted(NORM.glob("frame_*.jpg"))

# Find indices of these frames in the sorted list
idx_128 = next((i for i, p in enumerate(norm_paths) if p.name == "frame_000128.jpg"), -1)
idx_149 = next((i for i, p in enumerate(norm_paths) if p.name == "frame_000149.jpg"), -1)

print(f"frame_000128 is at norm_paths index {idx_128}")
print(f"frame_000149 is at norm_paths index {idx_149}")
print(f"Distance: {abs(idx_149 - idx_128) - 1} frames between them")

cfg = DedupeConfig()
print(f"\nStage E lookback window: {cfg.progressive_lookback}")
print(f"Can they be matched in Stage E? {abs(idx_149 - idx_128) <= cfg.progressive_lookback}")

# But wait, they also need to survive to Stage E (D output)
# Let me check if they're consecutive in the norm list
if idx_128 < idx_149:
    between = norm_paths[idx_128+1:idx_149]
    print(f"\nFrames between them: {[p.name for p in between]}")
