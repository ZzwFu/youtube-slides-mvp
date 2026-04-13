"""Evaluate a finished pipeline run against an approved benchmark."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.benchmark import RUNS_DIR, evaluate_run_directory, write_benchmark_evaluation, write_benchmark_evaluation_markdown

def _fmt(value: object) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _print_report(report: dict[str, object]) -> None:
    print(f"run_id        : {report.get('run_id')}")
    print(f"benchmark     : {report.get('benchmark_id') or 'N/A'}")
    print(f"mode          : {report.get('comparison_mode')}")
    print(f"page_count    : {report.get('page_count')}")
    print(f"expected      : {_fmt(report.get('expected_pages'))}")
    print(f"matched_pages : {_fmt(report.get('matched_pages'))}")
    print(f"precision     : {_fmt(report.get('precision'))}")
    print(f"recall        : {_fmt(report.get('recall'))}")
    print(f"f1            : {_fmt(report.get('f1'))}")
    print(f"miss_rate     : {_fmt(report.get('miss_rate'))}  (limit {report.get('gate_max_miss_rate')})")
    print(f"excess_rate   : {_fmt(report.get('excess_rate'))}  (limit {report.get('gate_max_excess_rate')})")
    print(f"missing_pages : {_fmt(report.get('missing_count'))}")
    print(f"extra_pages   : {_fmt(report.get('extra_count'))}")
    if report.get("reason"):
        print(f"reason        : {report.get('reason')}")
    print(f"gate          : {report.get('gate')}")


def evaluate(run_id: str, benchmark_id: str | None = None) -> int:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        print(f"ERROR: run not found: {run_dir}", file=sys.stderr)
        return 1

    report = evaluate_run_directory(run_dir, benchmark_id=benchmark_id)
    json_path = run_dir / "artifacts" / "benchmark_eval.json"
    md_path = run_dir / "artifacts" / "benchmark_eval.md"
    write_benchmark_evaluation(json_path, report)
    write_benchmark_evaluation_markdown(md_path, report)
    _print_report(report)
    return 0 if report.get("gate") == "pass" else 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    run_id = sys.argv[1]
    benchmark_id = sys.argv[2] if len(sys.argv) > 2 else None
    return evaluate(run_id, benchmark_id)


if __name__ == "__main__":
    sys.exit(main())
