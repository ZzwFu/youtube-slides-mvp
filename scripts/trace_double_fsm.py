"""Trace the current _complete_pages behavior with double-FSM."""
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

# Novelty refill (default min_gap_sec=20)
selected_orig, selected_rows, rescued = _cli._refill_gaps(
    selected_orig=selected_orig,
    selected_rows=selected_rows,
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    strategy="novelty",
)
print(f"After novelty: {len(selected_orig)} (rescued={rescued})")

# Check if 991 is present after novelty
has_991 = any(p.name == "frame_000991.jpg" for p in selected_orig)
print(f"991 present after novelty: {has_991}")

# Show frames around t=990 after novelty
print("Frames around t=940-1040 after novelty:")
for p, r in sorted(zip(selected_orig, selected_rows), key=lambda x: float(x[1].get("timestamp_sec", 0))):
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  {p.name} t={t:.0f}s")

# Run _complete_pages (current code = double-FSM)
out_orig, out_rows, completed, collapsed, dropped = _cli._complete_pages(
    selected_orig=selected_orig,
    selected_rows=selected_rows,
    frame_rows=frame_rows,
    frames_raw_dir=frames_raw_dir,
    mode="iterative",
)
print(f"\nAfter _complete_pages: {len(out_orig)} (completed={completed}, collapsed={collapsed}, dropped={dropped})")

has_991_after = any(p.name == "frame_000991.jpg" for p in out_orig)
print(f"991 present after _complete_pages: {has_991_after}")

# Show what's around t=990
print("Frames around t=940-1040 after _complete_pages:")
for p, r in sorted(zip(out_orig, out_rows), key=lambda x: float(x[1].get("timestamp_sec", 0))):
    t = float(r.get("timestamp_sec", 0))
    if 940 <= t <= 1040:
        print(f"  {p.name} t={t:.0f}s")
