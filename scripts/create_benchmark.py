"""Create or update a benchmark from a manually approved run."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.benchmark import RUNS_DIR, build_benchmark_from_run, write_benchmark


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", help="Approved run id under runs/")
    parser.add_argument("benchmark_id", nargs="?", help="Benchmark id to write under benchmarks/")
    parser.add_argument("--profile", dest="video_profile", help="Optional profile label, e.g. plain/progressive/fade")
    parser.add_argument("--tolerance-ms", type=int, default=3000, help="Timestamp tolerance for future eval matching")
    parser.add_argument("--notes", default=None, help="Optional operator note stored with the benchmark")
    args = parser.parse_args()

    run_dir = RUNS_DIR / args.run_id
    if not run_dir.exists():
        print(f"ERROR: run not found: {run_dir}", file=sys.stderr)
        return 1

    payload = build_benchmark_from_run(
        run_dir,
        benchmark_id=args.benchmark_id,
        video_profile=args.video_profile,
        tolerance_ms=args.tolerance_ms,
        notes=args.notes,
    )
    out_path = write_benchmark(str(payload["benchmark_id"]), payload)
    print(f"benchmark_id  : {payload['benchmark_id']}")
    print(f"approved_run  : {payload['approved_run_id']}")
    print(f"expected      : {payload['expected_pages']}")
    print(f"tolerance_ms  : {payload['tolerance_ms']}")
    print(f"output        : {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())