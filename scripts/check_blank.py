"""Check if frame_000991 is classified as blank transition frame."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.cli import _is_blank_transition_frame
from PIL import Image
import numpy as np

frames = Path("runs/slide-v3-full-progressive/frames_raw")
for name in ["frame_000948.jpg", "frame_000991.jpg", "frame_001024.jpg"]:
    p = frames / name
    if not p.exists():
        print(f"{name}: MISSING")
        continue
    blank = _is_blank_transition_frame(p)
    img = Image.open(p).convert("L").resize((256, 144), Image.Resampling.BILINEAR)
    arr = np.asarray(img, dtype=np.uint8)
    mean_v = float(arr.mean())
    std_v = float(arr.std())
    gy = np.abs(np.diff(arr.astype(np.float32), axis=0))
    gx = np.abs(np.diff(arr.astype(np.float32), axis=1))
    ev = float(np.var(np.concatenate([gx.ravel(), gy.ravel()])))
    print(f"{name}: mean={mean_v:.1f} std={std_v:.1f} edge_var={ev:.1f} blank={blank}")
