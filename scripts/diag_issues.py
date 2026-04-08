"""Diagnostic: analyse missing first page, duplicate pairs, and p23 context."""
import sys, json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import _load_gray, _diff, _reveal, _motion_ratio, _hash_bits, _hamming

RUN    = Path(__file__).parent.parent / "runs/slide-20260408-051954"
FRAMES = RUN / "frames_raw"
NORM   = RUN / "frames_norm"

slides = json.loads((RUN / "artifacts/slides.json").read_text())["slides"]
by_page = {r["page"]: r for r in slides}

# ── 1. First 25 raw frames ────────────────────────────────────────────────────
print("=== First 25 frames (raw) – looking for title/first page ===")
for i in range(1, 26):
    fn = f"frame_{i:06d}.jpg"
    p = FRAMES / fn
    if not p.exists():
        continue
    arr = _load_gray(p)
    print(f"  frame_{i:06d}  t={i-1:3d}s  mean={arr.mean():.1f}  std={arr.std():.1f}")

# ── 2. Diff between reported duplicate pairs ─────────────────────────────────
print("\n=== Duplicate pair diffs ===")
pairs = [(4,5),(8,9),(16,17),(19,20),(21,22),(31,32),(37,38),(39,40),(47,48)]
for pa, pb in pairs:
    ra = by_page.get(pa)
    rb = by_page.get(pb)
    if not ra or not rb:
        print(f"  p{pa:02d}/p{pb:02d}  MISSING in slides")
        continue
    # prefer norm frames, fallback to raw
    fa = NORM / ra["frame_name"]
    fb = NORM / rb["frame_name"]
    if not fa.exists():
        fa = FRAMES / ra["frame_name"]
    if not fb.exists():
        fb = FRAMES / rb["frame_name"]
    a = _load_gray(fa)
    b = _load_gray(fb)
    d      = _diff(a, b)
    mr     = _motion_ratio(a, b)
    cover, add = _reveal(a, b)
    hd     = _hamming(_hash_bits(a), _hash_bits(b))
    dt     = rb["timestamp_sec"] - ra["timestamp_sec"]
    print(f"  p{pa:02d}/p{pb:02d}  dt={dt:+.0f}s  diff={d:.4f}  motion={mr:.4f}  hamming={hd:3d}  cover={cover:.3f}  add={add:.3f}")

# ── 3. Context around p23 (incomplete info) ────────────────────────────────
print("\n=== Pages 21-26 context (around incomplete p23) ===")
for pg in range(21, 27):
    r = by_page.get(pg)
    if r:
        print(f"  p{pg:02d}  t={r['timestamp_sec']:7.1f}s  {r['frame_name']}")
