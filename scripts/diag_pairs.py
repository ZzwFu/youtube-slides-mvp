"""Diagnose specific frame pairs for progressive duplicate investigation."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from youtube_slides_mvp.dedupe import (
    _hamming, _diff, _reveal, _directional_change,
    _motion_ratio, _dark_cover, _hash_bits, _load_gray,
)

run = Path("runs/slide-v2-full-progressive/frames_raw")

def metrics(f1, f2):
    a = _load_gray(run / f1)
    b = _load_gray(run / f2)
    ha = _hash_bits(a)
    hb = _hash_bits(b)
    hd = _hamming(ha, hb)
    d = _diff(a, b)
    neg, pos = _reveal(a, b)
    mr = _motion_ratio(a, b)
    cov, new_pix = _dark_cover(a, b)
    dn, dp = _directional_change(a, b)
    print(f"  hd={hd} diff={d:.4f} rev(neg={neg:.4f},pos={pos:.4f}) "
          f"motion={mr:.4f} dark(cov={cov:.4f},new={new_pix:.4f}) "
          f"dir(neg={dn:.4f},pos={dp:.4f})")

pairs = [
    ("frame_000698.jpg", "frame_000702.jpg", "p28 vs p29"),
    ("frame_000702.jpg", "frame_000708.jpg", "p29 vs p30"),
    ("frame_000698.jpg", "frame_000708.jpg", "p28 vs p30"),
    ("frame_000801.jpg", "frame_000802.jpg", "p34 vs p35"),
    ("frame_000802.jpg", "frame_000820.jpg", "p35 vs p36"),
    ("frame_000801.jpg", "frame_000820.jpg", "p34 vs p36"),
    ("frame_000688.jpg", "frame_000698.jpg", "p27 vs p28"),
]

for f1, f2, label in pairs:
    print(label)
    metrics(f1, f2)

print("\n--- Non-additive (legit different) pairs for contrast ---")
legit_pairs = [
    ("frame_000570.jpg", "frame_000584.jpg", "p22 vs p23"),
    ("frame_000584.jpg", "frame_000596.jpg", "p23 vs p24"),
    ("frame_000596.jpg", "frame_000600.jpg", "p24 vs p25"),
    ("frame_000743.jpg", "frame_000779.jpg", "p32 vs p33"),
    ("frame_000820.jpg", "frame_000878.jpg", "p36 vs p37"),
]

for f1, f2, label in legit_pairs:
    print(label)
    metrics(f1, f2)
