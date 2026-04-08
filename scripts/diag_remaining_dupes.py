"""
Diagnose remaining duplicate pairs that Stage E secondary check missed.
"""
import sys, json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import _load_gray, _diff, _dark_cover, _directional_change, DedupeConfig

RUN    = Path(__file__).parent.parent / "runs/slide-20260408-054947"
FRAMES = RUN / "frames_raw"

slides = json.loads((RUN / "artifacts/slides.json").read_text())["slides"]
by_page = {r["page"]: r for r in slides}

cfg = DedupeConfig()
print(f"=== Stage E Secondary Additive Reveal Config ===")
print(f"  additive_reveal_diff_th:    {cfg.additive_reveal_diff_th}")
print(f"  additive_neg_max:           {cfg.additive_neg_max}")
print(f"  additive_dark_cover_th:     {cfg.additive_dark_cover_th}")
print(f"  additive_dark_add_th:       {cfg.additive_dark_add_th}")

print("\n=== Analysis of Reported Remaining Duplicates ===")
pairs = [(8,9),(16,17),(19,20),(35,36),(43,44)]

for pa, pb in pairs:
    ra = by_page.get(pa)
    rb = by_page.get(pb)
    if not ra or not rb:
        print(f"p{pa:02d}/p{pb:02d}  MISSING in slides")
        continue
    
    fa = FRAMES / ra["frame_name"]
    fb = FRAMES / rb["frame_name"]
    
    if not fa.exists() or not fb.exists():
        print(f"p{pa:02d}/p{pb:02d}  MISSING frame files")
        continue
    
    a = _load_gray(fa)
    b = _load_gray(fb)
    
    d      = _diff(a, b)
    dc, da = _dark_cover(a, b)
    neg, pos = _directional_change(a, b)
    dt     = rb["timestamp_sec"] - ra["timestamp_sec"]
    
    # Check against Stage E secondary criteria
    passes_diff = d <= cfg.additive_reveal_diff_th
    passes_neg  = neg <= cfg.additive_neg_max
    passes_dc   = dc >= cfg.additive_dark_cover_th
    passes_da   = da <= cfg.additive_dark_add_th
    
    print(f"\np{pa:02d}/p{pb:02d}  dt={dt:+.0f}s  t={ra['timestamp_sec']:.0f}→{rb['timestamp_sec']:.0f}s")
    print(f"  diff={d:.4f}  [threshold={cfg.additive_reveal_diff_th}, pass={passes_diff}]")
    print(f"  neg={neg:.5f}   [threshold={cfg.additive_neg_max}, pass={passes_neg}]")
    print(f"  dark_cover={dc:.3f}  [threshold={cfg.additive_dark_cover_th}, pass={passes_dc}]")
    print(f"  dark_add={da:.3f}  [threshold={cfg.additive_dark_add_th}, pass={passes_da}]")
    print(f"  pos={pos:.5f}  (brightness added)")
    
    if passes_diff and passes_neg and passes_dc and passes_da:
        print(f"  ✓ SHOULD HAVE BEEN MERGED by Stage E secondary")
    else:
        print(f"  ✗ Failed {[c for c, p in [('diff',passes_diff),('neg',passes_neg),('dc',passes_dc),('da',passes_da)] if not p]}")
