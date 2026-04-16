"""Diff v3 full output against baseline to find missing/extra pages. (Optimized)"""

import json
import sys
from typing import List, Tuple

# ====================== 配置 ======================
tolerance = 3.0  # 秒
baseline_path = 'benchmarks/slide-20260410-122639/expected_pages.json'
run = sys.argv[1] if len(sys.argv) > 1 else 'runs/slide-v3-full-progressive'
run_path = f'{run}/artifacts/slides.json'

# ====================== 加载数据 ======================
with open(baseline_path) as f:
    baseline = json.load(f)['pages']

with open(run_path) as f:
    v3_full = json.load(f)['slides']

# 提取 (timestamp, frame_name, original_index)
b_ts: List[Tuple[float, str, int]] = [
    (p['timestamp_sec'], p.get('frame_name', ''), i) 
    for i, p in enumerate(baseline)
]

v_ts: List[Tuple[float, str, int]] = [
    (s['timestamp_sec'], s.get('frame_name', ''), i) 
    for i, s in enumerate(v3_full)
]

print(f"Baseline: {len(b_ts)} pages")
print(f"Run     : {len(v_ts)} pages\n")

# ====================== 双指针匹配 ======================
missing = []
extra = []

i = j = 0  # i: baseline 指针, j: v3_full 指针

while i < len(b_ts) and j < len(v_ts):
    bt, bn, _ = b_ts[i]
    vt, vn, _ = v_ts[j]
    
    diff = bt - vt
    
    if abs(diff) <= tolerance:
        # 匹配成功，两个指针都前进
        i += 1
        j += 1
    elif diff < 0:
        # baseline 的时间更早 → missing
        missing.append((i + 1, bt, bn))
        i += 1
    else:
        # run 的时间更早 → extra
        extra.append((j + 1, vt, vn))
        j += 1

# 处理尾部剩余
while i < len(b_ts):
    bt, bn, _ = b_ts[i]
    missing.append((i + 1, bt, bn))
    i += 1

while j < len(v_ts):
    vt, vn, _ = v_ts[j]
    extra.append((j + 1, vt, vn))
    j += 1

# ====================== 输出 ======================
print(f"MISSING from run ({len(missing)}):")
for p, t, n in missing:
    print(f"  baseline p{p:2d}: t={t:6.1f}s  {n}")

print(f"\nEXTRA in run ({len(extra)}):")
for p, t, n in extra:
    print(f"  run p{p:2d}: t={t:6.1f}s  {n}")