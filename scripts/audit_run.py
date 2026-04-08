"""Audit a run for duplicate-page pairs and missing-page candidates.

Usage:
  PYTHONPATH=src python scripts/audit_run.py <run_id>
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from youtube_slides_mvp.dedupe import _dark_cover, _directional_change


def _load_gray(path: Path) -> np.ndarray:
    return np.asarray(
        Image.open(path).convert("L").resize((256, 144), Image.Resampling.BILINEAR),
        dtype=np.uint8,
    )


def _diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))) / 255.0)


def _std(a: np.ndarray) -> float:
    return float(a.astype(np.float32).std())


def _fmt(v: float) -> str:
    return f"{v:.6f}"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=src python scripts/audit_run.py <run_id>")
        return 2

    run_id = sys.argv[1]
    root = Path(__file__).resolve().parent.parent
    run_dir = root / "runs" / run_id
    slides_path = run_dir / "artifacts" / "slides.json"
    manifest_path = run_dir / "artifacts" / "frame_manifest.json"
    frames_raw_dir = run_dir / "frames_raw"
    out_dir = run_dir / "artifacts" / "audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not slides_path.exists() or not manifest_path.exists() or not frames_raw_dir.exists():
        print(f"run not complete or missing files: {run_id}")
        return 1

    slides = json.loads(slides_path.read_text(encoding="utf-8")).get("slides", [])
    frame_rows = json.loads(manifest_path.read_text(encoding="utf-8")).get("frames", [])
    selected_names = {str(r.get("frame_name", "")) for r in slides}

    by_ts = sorted(frame_rows, key=lambda r: float(r.get("timestamp_sec", 0.0)))
    cache: dict[str, np.ndarray] = {}

    def load_name(name: str) -> np.ndarray | None:
        if not name:
            return None
        if name not in cache:
            p = frames_raw_dir / name
            if not p.exists():
                return None
            cache[name] = _load_gray(p)
        return cache[name]

    pair_rows: list[dict[str, str]] = []
    missing_rows: list[dict[str, str]] = []

    # Duplicate audit on adjacent selected pages.
    for i in range(len(slides) - 1):
        a = slides[i]
        b = slides[i + 1]
        an = str(a.get("frame_name", ""))
        bn = str(b.get("frame_name", ""))
        aa = load_name(an)
        bb = load_name(bn)
        if aa is None or bb is None:
            continue

        d = _diff(aa, bb)
        neg, pos = _directional_change(aa, bb)
        dc, da = _dark_cover(aa, bb)
        dt = float(b.get("timestamp_sec", 0.0)) - float(a.get("timestamp_sec", 0.0))

        kind = ""
        confidence = ""
        # Strict near-exact duplicate.
        if d <= 0.012 and neg <= 0.002 and dc >= 0.94 and da <= 0.05:
            kind = "exact_or_near_exact"
            confidence = "high"
        # Soft additive duplicate: catches progressive reveals that are still
        # visually repetitive but not pixel-near-identical.
        elif d <= 0.08 and neg <= 0.001 and da <= 0.35 and pos >= 0.02 and dc >= 0.60:
            kind = "additive_reveal_duplicate"
            confidence = "medium"

        if kind:
            pair_rows.append(
                {
                    "prev_page": str(i + 1),
                    "curr_page": str(i + 2),
                    "kind": kind,
                    "confidence": confidence,
                    "prev_frame": an,
                    "curr_frame": bn,
                    "delta_ts": _fmt(dt),
                    "diff": _fmt(d),
                    "neg": _fmt(neg),
                    "pos": _fmt(pos),
                    "dark_cover": _fmt(dc),
                    "dark_add": _fmt(da),
                }
            )

    # Missing-page candidate audit on wide timestamp gaps.
    for i in range(len(slides) - 1):
        a = slides[i]
        b = slides[i + 1]
        ta = float(a.get("timestamp_sec", 0.0))
        tb = float(b.get("timestamp_sec", 0.0))
        dt = tb - ta
        if dt < 18.0:
            continue

        an = str(a.get("frame_name", ""))
        bn = str(b.get("frame_name", ""))
        aa = load_name(an)
        bb = load_name(bn)
        if aa is None or bb is None:
            continue
        d_ab = _diff(aa, bb)

        best: tuple[float, str, float, float, float] | None = None
        for row in by_ts:
            t = float(row.get("timestamp_sec", 0.0))
            if t <= ta + 1.0 or t >= tb - 1.0:
                continue
            name = str(row.get("frame_name", ""))
            if not name or name in selected_names:
                continue
            cc = load_name(name)
            if cc is None or _std(cc) < 12.0:
                continue

            d_ac = _diff(aa, cc)
            d_cb = _diff(cc, bb)
            # Candidate frame should be significantly different from both ends,
            # and not just one endpoint's near-copy.
            if d_ac < 0.08 or d_cb < 0.08:
                continue
            score = min(d_ac, d_cb) - 0.5 * d_ab
            if score < 0.03:
                continue
            if best is None or score > best[0]:
                best = (score, name, t, d_ac, d_cb)

        if best is not None:
            score, cname, ct, d_ac, d_cb = best
            missing_rows.append(
                {
                    "prev_page": str(i + 1),
                    "next_page": str(i + 2),
                    "prev_frame": an,
                    "next_frame": bn,
                    "gap_sec": _fmt(dt),
                    "prev_next_diff": _fmt(d_ab),
                    "candidate_frame": cname,
                    "candidate_ts": _fmt(ct),
                    "diff_prev_candidate": _fmt(d_ac),
                    "diff_candidate_next": _fmt(d_cb),
                    "score": _fmt(score),
                }
            )

    pair_csv = out_dir / "pair_alerts.csv"
    miss_csv = out_dir / "missing_candidates.csv"
    report_md = out_dir / "audit_report.md"

    with pair_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "prev_page",
            "curr_page",
            "kind",
            "confidence",
            "prev_frame",
            "curr_frame",
            "delta_ts",
            "diff",
            "neg",
            "pos",
            "dark_cover",
            "dark_add",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(pair_rows)

    with miss_csv.open("w", newline="", encoding="utf-8") as f:
        fieldnames = [
            "prev_page",
            "next_page",
            "prev_frame",
            "next_frame",
            "gap_sec",
            "prev_next_diff",
            "candidate_frame",
            "candidate_ts",
            "diff_prev_candidate",
            "diff_candidate_next",
            "score",
        ]
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(missing_rows)

    lines = [
        f"# Audit Report ({run_id})",
        "",
        f"- Selected pages: {len(slides)}",
        f"- Pair alerts: {len(pair_rows)}",
        f"- Missing candidates: {len(missing_rows)}",
        "",
        "## Pair Alerts",
    ]
    if not pair_rows:
        lines.append("- none")
    else:
        for r in pair_rows:
            lines.append(
                "- "
                f"{r['prev_page']}/{r['curr_page']} {r['kind']} ({r['confidence']}), "
                f"d={r['diff']} neg={r['neg']} pos={r['pos']} dc={r['dark_cover']} da={r['dark_add']}"
            )

    lines.extend(["", "## Missing Candidates"])
    if not missing_rows:
        lines.append("- none")
    else:
        for r in missing_rows[:20]:
            lines.append(
                "- "
                f"{r['prev_page']}->{r['next_page']} gap={r['gap_sec']}s candidate={r['candidate_frame']}@{r['candidate_ts']}s "
                f"score={r['score']} d(prev,cand)={r['diff_prev_candidate']} d(cand,next)={r['diff_candidate_next']}"
            )

    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Audit done: {run_id}")
    print(f"  pair alerts: {len(pair_rows)} -> {pair_csv}")
    print(f"  missing candidates: {len(missing_rows)} -> {miss_csv}")
    print(f"  report: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
