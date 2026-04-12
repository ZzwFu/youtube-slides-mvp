"""
Evaluate a finished pipeline run against a golden benchmark.

Usage:
    python scripts/eval_run.py <run_id> [<benchmark_id>]

If benchmark_id is omitted it defaults to the run's source_run (for reuse-frames
runs) or the run itself. The script looks for:
    benchmarks/<benchmark_id>/expected_pages.json

Output (to stdout):
    page_count, expected, miss_rate, excess_rate, gate (pass|fail|unknown)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RUNS_DIR = Path(__file__).parent.parent / "runs"
BENCHMARKS_DIR = Path(__file__).parent.parent / "benchmarks"


def _load_slides_json(run_dir: Path) -> dict:
    slides_json = run_dir / "artifacts" / "slides.json"
    if not slides_json.exists():
        raise FileNotFoundError(f"slides.json not found: {slides_json}")
    return json.loads(slides_json.read_text())


def _load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text())


def evaluate(run_id: str, benchmark_id: str | None = None) -> int:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        print(f"ERROR: run not found: {run_dir}", file=sys.stderr)
        return 1

    slides_data = _load_slides_json(run_dir)
    page_count = int(slides_data.get("count", len(slides_data.get("slides", []))))

    # Resolve benchmark_id: use explicit arg, else run_id
    if benchmark_id is None:
        benchmark_id = run_id

    bench_file = BENCHMARKS_DIR / benchmark_id / "expected_pages.json"
    if not bench_file.exists():
        print(f"WARNING: no benchmark found at {bench_file} — reporting without expected_pages")
        print(f"run_id        : {run_id}")
        print(f"page_count    : {page_count}")
        print(f"expected      : N/A")
        print(f"miss_rate     : N/A")
        print(f"excess_rate   : N/A")
        print(f"gate          : unknown")
        return 0

    bench = json.loads(bench_file.read_text())
    expected = int(bench["expected_pages"])

    miss_rate = max(0.0, (expected - page_count) / expected)
    excess_rate = max(0.0, (page_count - expected) / expected)

    max_miss = 0.15
    max_excess = 0.20
    if miss_rate <= max_miss and excess_rate <= max_excess:
        gate = "pass"
    else:
        gate = "fail"

    print(f"run_id        : {run_id}")
    print(f"benchmark     : {benchmark_id}")
    print(f"page_count    : {page_count}")
    print(f"expected      : {expected}")
    print(f"miss_rate     : {miss_rate:.4f}  (limit {max_miss})")
    print(f"excess_rate   : {excess_rate:.4f}  (limit {max_excess})")
    print(f"gate          : {gate}")

    return 0 if gate == "pass" else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run_id = sys.argv[1]
    benchmark_id = sys.argv[2] if len(sys.argv) > 2 else None
    return evaluate(run_id, benchmark_id)


if __name__ == "__main__":
    sys.exit(main())
