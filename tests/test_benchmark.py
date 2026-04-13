import json
from pathlib import Path

from src.youtube_slides_mvp.benchmark import (
	build_benchmark_from_run,
	evaluate_run_directory,
	evaluate_slides_against_benchmark,
	resolve_benchmark_id_for_run,
)


def _write_json(path: Path, payload: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def _write_run(
	root: Path,
	run_id: str,
	slides: list[dict],
	url: str = "http://example.com/watch?v=demo",
	src_run: str | None = None,
) -> Path:
	run_dir = root / "runs" / run_id
	artifacts_dir = run_dir / "artifacts"
	artifacts_dir.mkdir(parents=True, exist_ok=True)
	manifest = {"url": url, "metadata": {}}
	if src_run is not None:
		manifest["metadata"]["download"] = {"src_run": src_run}
	_write_json(run_dir / "manifest.json", manifest)
	_write_json(artifacts_dir / "slides.json", {"slides": slides})
	return run_dir


def test_build_benchmark_from_run_defaults_to_run_id(tmp_path: Path) -> None:
	run_dir = _write_run(
		tmp_path,
		"approved-run-001",
		slides=[
			{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 1.0},
			{"page": 2, "frame_name": "frame_000005.jpg", "timestamp_ms": 5000},
		],
		url="http://example.com/watch?v=video-a",
		src_run="raw-run-001",
	)

	payload = build_benchmark_from_run(
		run_dir,
		video_profile="plain",
		tolerance_ms=2500,
		notes="approved by operator",
	)

	assert payload["benchmark_id"] == "approved-run-001"
	assert payload["approved_run_id"] == "approved-run-001"
	assert payload["source_run_id"] == "raw-run-001"
	assert payload["expected_pages"] == 2
	assert payload["tolerance_ms"] == 2500
	assert payload["video_profile"] == "plain"
	assert payload["source_url"] == "http://example.com/watch?v=video-a"
	assert payload["pages"][0]["timestamp_ms"] == 1000
	assert payload["pages"][1]["timestamp_ms"] == 5000


def test_resolve_benchmark_id_prefers_src_run(tmp_path: Path) -> None:
	run_dir = _write_run(
		tmp_path,
		"candidate-run-001",
		slides=[{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 1.0}],
		src_run="benchmark-run-001",
	)
	_write_json(
		tmp_path / "benchmarks" / "benchmark-run-001" / "expected_pages.json",
		{
			"benchmark_id": "benchmark-run-001",
			"expected_pages": 1,
		},
	)

	resolved, reason = resolve_benchmark_id_for_run(run_dir, benchmarks_dir=tmp_path / "benchmarks")
	assert resolved == "benchmark-run-001"
	assert reason is None


def test_resolve_benchmark_id_uses_src_run_when_source_url_has_multiple_matches(tmp_path: Path) -> None:
	run_dir = _write_run(
		tmp_path,
		"candidate-run-003",
		slides=[{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 1.0}],
		url="http://example.com/watch?v=shared",
		src_run="benchmark-run-003",
	)
	_write_json(
		tmp_path / "benchmarks" / "benchmark-run-003" / "expected_pages.json",
		{
			"benchmark_id": "benchmark-run-003",
			"source_url": "http://example.com/watch?v=shared",
			"expected_pages": 1,
		},
	)
	_write_json(
		tmp_path / "benchmarks" / "other-run-004" / "expected_pages.json",
		{
			"benchmark_id": "other-run-004",
			"source_url": "http://example.com/watch?v=shared",
			"expected_pages": 2,
		},
	)

	resolved, reason = resolve_benchmark_id_for_run(run_dir, benchmarks_dir=tmp_path / "benchmarks")
	assert resolved == "benchmark-run-003"
	assert reason is None


def test_resolve_benchmark_id_prefers_manifest_hint(tmp_path: Path) -> None:
	run_dir = _write_run(
		tmp_path,
		"candidate-run-004",
		slides=[{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 1.0}],
	)
	manifest_path = run_dir / "manifest.json"
	manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
	manifest["metadata"]["benchmark_eval"] = {"benchmark_id": "hinted-benchmark"}
	manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")

	_write_json(
		tmp_path / "benchmarks" / "hinted-benchmark" / "expected_pages.json",
		{
			"benchmark_id": "hinted-benchmark",
			"expected_pages": 1,
		},
	)

	resolved, reason = resolve_benchmark_id_for_run(run_dir, benchmarks_dir=tmp_path / "benchmarks")
	assert resolved == "hinted-benchmark"
	assert reason is None


def test_evaluate_slides_against_benchmark_page_aligned() -> None:
	benchmark = {
		"benchmark_id": "video-c",
		"expected_pages": 3,
		"tolerance_ms": 500,
		"pages": [
			{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_ms": 1000},
			{"page": 2, "frame_name": "frame_000004.jpg", "timestamp_ms": 4000},
			{"page": 3, "frame_name": "frame_000007.jpg", "timestamp_ms": 7000},
		],
	}
	actual = [
		{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_ms": 1000},
		{"page": 2, "frame_name": "frame_000005.jpg", "timestamp_ms": 5200},
		{"page": 3, "frame_name": "frame_000009.jpg", "timestamp_ms": 9000},
	]

	report = evaluate_slides_against_benchmark(actual, benchmark)

	assert report["comparison_mode"] == "page-aligned"
	assert report["matched_pages"] == 1
	assert report["missing_count"] == 2
	assert report["extra_count"] == 2
	assert report["precision"] == 0.333333
	assert report["recall"] == 0.333333
	assert report["miss_rate"] == 0.666667
	assert report["excess_rate"] == 0.666667
	assert report["gate"] == "fail"


def test_evaluate_slides_against_benchmark_count_only() -> None:
	benchmark = {
		"benchmark_id": "video-d",
		"expected_pages": 3,
	}
	actual = [
		{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_ms": 1000},
		{"page": 2, "frame_name": "frame_000002.jpg", "timestamp_ms": 2000},
		{"page": 3, "frame_name": "frame_000003.jpg", "timestamp_ms": 3000},
		{"page": 4, "frame_name": "frame_000004.jpg", "timestamp_ms": 4000},
	]

	report = evaluate_slides_against_benchmark(actual, benchmark)

	assert report["comparison_mode"] == "count-only"
	assert report["precision"] is None
	assert report["recall"] is None
	assert report["miss_rate"] == 0.0
	assert report["excess_rate"] == 0.333333
	assert report["gate"] == "fail"


def test_evaluate_run_directory_unknown_without_benchmark(tmp_path: Path) -> None:
	run_dir = _write_run(
		tmp_path,
		"candidate-run-002",
		slides=[{"page": 1, "frame_name": "frame_000001.jpg", "timestamp_sec": 1.0}],
		url="http://example.com/watch?v=video-e",
	)

	report = evaluate_run_directory(run_dir, benchmarks_dir=tmp_path / "benchmarks")

	assert report["comparison_mode"] == "missing-benchmark"
	assert report["gate"] == "unknown"
	assert report["gate_pass"] is False
	assert report["reason"] == "no benchmark matched this run"
