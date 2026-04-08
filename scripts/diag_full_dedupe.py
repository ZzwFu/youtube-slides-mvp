"""
Run full dedupe_frames on the 2040 norm frames and inspect Stage E output.
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import DedupeConfig, dedupe_frames

RUN  = Path(__file__).parent.parent / "runs/slide-20260408-054947"
NORM = RUN / "frames_norm"

norm_paths = sorted(NORM.glob("frame_*.jpg"))
print(f"Running dedupe_frames on {len(norm_paths)} normalized frames...")
selected, stats = dedupe_frames(norm_paths, DedupeConfig())

print(f"\nDedupe stats: {stats}")
print(f"Output pages: {len(selected)}")

# Map selected frames back to timestamps
frame_manifest = json.loads((RUN / "artifacts/frame_manifest.json").read_text())
by_name = {str(r["frame_name"]): r for r in frame_manifest["frames"]}

print("\nSelected frames (first 30):")
for page, path in enumerate(selected[:30], start=1):
    row = by_name.get(path.name, {})
    ts = row.get("timestamp_sec", 0)
    print(f"  p{page:02d}  t={float(ts):7.1f}s  {path.name}")

# Check specifically for p08-p09 area
print("\nSearching for frames around original p08/p09 (t~127-149s):")
for page, path in enumerate(selected, start=1):
    row = by_name.get(path.name, {})
    ts = float(row.get("timestamp_sec", 0))
    if 125 < ts < 155:
        print(f"  p{page:02d}  t={ts:7.1f}s  {path.name}")
