"""
Deep-trace dedupe for first N frames to find exactly where frame_000011 is dropped.
Also shows dark-pixel coverage for duplicate pairs.
"""
import sys, json
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from youtube_slides_mvp.dedupe import (
    _load_gray, _diff, _reveal, _motion_ratio, _hash_bits, _hamming,
    _directional_change, DedupeConfig
)

RUN    = Path(__file__).parent.parent / "runs/slide-20260408-051954"
FRAMES = RUN / "frames_raw"
NORM   = RUN / "frames_norm"

# ── helper: dark-pixel coverage (text-on-white metric) ────────────────────────
def _dark_cover(a: np.ndarray, b: np.ndarray):
    """Fraction of prev dark content (text) preserved in curr, and fraction new."""
    pm = a <= np.percentile(a, 30)
    cm = b <= np.percentile(b, 30)
    pn = int(pm.sum())
    cn = int(cm.sum())
    if pn == 0 or cn == 0:
        return 0.0, 1.0
    inter = int(np.logical_and(pm, cm).sum())
    new   = int(np.logical_and(~pm, cm).sum())
    return inter / float(pn), new / float(cn)


# ── 1. Trace Stage A through Stage G for first 30 norm frames ─────────────────
norm_paths = sorted(NORM.glob("frame_*.jpg"))[:30]
arrays  = [_load_gray(p) for p in norm_paths]
hashes  = [_hash_bits(a) for a in arrays]
cfg = DedupeConfig()

print("=== Stage A trace (first 30 norm frames) ===")
keep_idx = [0]
for i in range(1, len(norm_paths)):
    j = keep_idx[-1]
    d = _diff(arrays[j], arrays[i])
    hd = _hamming(hashes[j], hashes[i])
    cover, add = _reveal(arrays[j], arrays[i])
    merge = (d <= cfg.adjacent_diff_th and hd <= cfg.adjacent_hash_th) or \
            (cover >= cfg.reveal_cover_th and add <= cfg.reveal_add_th and d <= 0.12)
    action = "MERGE→" if merge else "KEEP  "
    if i < 30:
        print(f"  [{i:02d}] {norm_paths[i].name}  d={d:.4f}  hd={hd:3d}  cov={cover:.3f}  add={add:.3f}  {'MERGE→['+str(j)+']' if merge else 'KEEP'}")
    if merge:
        keep_idx[-1] = i
    else:
        keep_idx.append(i)

print(f"\n  Stage A kept indices (first 30 frames): {keep_idx}")
stage_a_names = [norm_paths[i].name for i in keep_idx]
print(f"  Stage A kept frames: {stage_a_names}")

# Show mean/std of stage A survivors
print("\n  Stage A survivor stats:")
for i in keep_idx:
    a = arrays[i]
    print(f"    frame_{i+1:06d}  mean={a.mean():.1f}  std={a.std():.1f}  (index {i})")

# ── 2. Stage C trace on Stage A output ────────────────────────────────────────
print("\n=== Stage C trace on Stage A output ===")
c_idx = [keep_idx[0]]
for k in range(1, len(keep_idx) - 1):
    p = keep_idx[k - 1]
    c = keep_idx[k]
    n = keep_idx[k + 1]
    d_pc = _diff(arrays[p], arrays[c])
    d_cn = _diff(arrays[c], arrays[n])
    d_pn = _diff(arrays[p], arrays[n])
    is_mid = d_pc > cfg.transition_mid_th and d_cn > cfg.transition_mid_th and d_pn < cfg.adjacent_diff_th
    print(f"  [{norm_paths[c].name}]  d_pc={d_pc:.4f}  d_cn={d_cn:.4f}  d_pn={d_pn:.4f}  is_mid={is_mid}")
    if not is_mid:
        c_idx.append(c)
if len(keep_idx) > 1:
    c_idx.append(keep_idx[-1])
print(f"  Stage C kept: {[norm_paths[i].name for i in c_idx]}")

# ── 3. Check dark-pixel coverage for the duplicate pairs ──────────────────────
print("\n=== Dark-pixel coverage for duplicate pairs ===")
slides = json.loads((RUN / "artifacts/slides.json").read_text())["slides"]
by_page = {r["page"]: r for r in slides}
pairs = [(4,5),(8,9),(16,17),(19,20),(21,22),(31,32),(37,38),(39,40),(47,48)]
for pa, pb in pairs:
    ra = by_page.get(pa); rb = by_page.get(pb)
    if not ra or not rb:
        continue
    fa = NORM / ra["frame_name"]
    fb = NORM / rb["frame_name"]
    if not fa.exists(): fa = FRAMES / ra["frame_name"]
    if not fb.exists(): fb = FRAMES / rb["frame_name"]
    a = _load_gray(fa); b = _load_gray(fb)
    d       = _diff(a, b)
    dc, da  = _dark_cover(a, b)
    br_c, br_a = _reveal(a, b)
    neg, pos = _directional_change(a, b)
    print(f"  p{pa:02d}/p{pb:02d}  diff={d:.4f}  dark_cover={dc:.3f}  dark_add={da:.3f}  bright_cov={br_c:.3f}  bright_add={br_a:.3f}  neg={neg:.4f}  pos={pos:.4f}")

# ── 4. Frames around p23 (timeline 421s-502s, looking for complete version) ────
print("\n=== Frames 421-502s (looking for complete p23 at t=430s) ===")
frame_rows = json.loads((RUN / "artifacts/frame_manifest.json").read_text())["frames"]
p23_arr = _load_gray(FRAMES / "frame_000431.jpg")
candidates = [r for r in frame_rows if 421.0 < float(r["timestamp_sec"]) < 502.0]
for r in candidates[::2]:  # every other frame to keep output manageable
    fn = r["frame_name"]
    fp = FRAMES / fn
    if not fp.exists(): continue
    arr = _load_gray(fp)
    d = _diff(p23_arr, arr)
    dc, da = _dark_cover(p23_arr, arr)
    print(f"  t={r['timestamp_sec']:6.0f}s  {fn}  diff_from_p23={d:.4f}  dark_cover={dc:.3f}  dark_add={da:.3f}  mean={arr.mean():.1f}")
