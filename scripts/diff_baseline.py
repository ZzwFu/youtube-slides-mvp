"""Diff v3 full output against baseline to find missing/extra pages."""
import json
import sys

baseline = json.load(open('benchmarks/slide-20260410-122639/expected_pages.json'))['pages']

run = sys.argv[1] if len(sys.argv) > 1 else 'runs/slide-v3-full-progressive'
v3_full = json.load(open(f'{run}/artifacts/slides.json'))['slides']

b_ts = [(p['timestamp_sec'], p.get('frame_name', '')) for p in baseline]
v_ts = [(s['timestamp_sec'], s.get('frame_name', '')) for s in v3_full]

print(f"Baseline: {len(b_ts)} pages")
print(f"Run:      {len(v_ts)} pages")

tolerance = 2.0

# Find missing: baseline pages not matched in run
matched_v = set()
missing = []
for i, (bt, bn) in enumerate(b_ts):
    found = False
    for j, (vt, vn) in enumerate(v_ts):
        if j not in matched_v and abs(bt - vt) <= tolerance:
            matched_v.add(j)
            found = True
            break
    if not found:
        missing.append((i + 1, bt, bn))

# Find extra: run pages not matched in baseline
matched_b = set()
extra = []
for j, (vt, vn) in enumerate(v_ts):
    found = False
    for i, (bt, bn) in enumerate(b_ts):
        if i not in matched_b and abs(bt - vt) <= tolerance:
            matched_b.add(i)
            found = True
            break
    if not found:
        extra.append((j + 1, vt, vn))

print(f"\nMISSING from run ({len(missing)}):")
for p, t, n in missing:
    print(f"  baseline p{p}: t={t:.1f}s {n}")

print(f"\nEXTRA in run ({len(extra)}):")
for p, t, n in extra:
    print(f"  run p{p}: t={t:.1f}s {n}")
