"""Compare novelty refill with min_gap_sec=15 vs 20."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.dedupe import DedupeConfig, dedupe_frames
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

# Run novelty with min_gap_sec=20 (pipeline default)
orig_20, rows_20, rescued_20 = _cli._refill_gaps(
    selected_orig=list(selected_orig),
    selected_rows=[dict(r) for r in selected_rows],
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    strategy="novelty",
    min_gap_sec=20.0,
)
names_20 = {p.name for p in orig_20}

# Run novelty with min_gap_sec=15
orig_15, rows_15, rescued_15 = _cli._refill_gaps(
    selected_orig=list(selected_orig),
    selected_rows=[dict(r) for r in selected_rows],
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    strategy="novelty",
    min_gap_sec=15.0,
)
names_15 = {p.name for p in orig_15}

print(f"min_gap_sec=20: {len(orig_20)} frames, rescued={rescued_20}")
print(f"min_gap_sec=15: {len(orig_15)} frames, rescued={rescued_15}")

extra = names_15 - names_20
missing = names_20 - names_15
print(f"\nExtra in 15 (not in 20): {sorted(extra)}")
print(f"Missing in 15 (in 20): {sorted(missing)}")

if extra:
    for name in sorted(extra):
        for r in rows_15:
            if r.get("frame_name") == name:
                print(f"  {name}: t={r.get('timestamp_sec', 0):.0f}s")
                break
