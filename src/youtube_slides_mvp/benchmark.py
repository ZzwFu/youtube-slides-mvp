from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
RUNS_DIR = ROOT_DIR / "runs"
BENCHMARKS_DIR = ROOT_DIR / "benchmarks"


def _read_json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def normalize_slide_row(row: dict[str, Any], fallback_page: int | None = None) -> dict[str, Any]:
	timestamp_ms_raw = row.get("timestamp_ms")
	if timestamp_ms_raw is None:
		timestamp_sec = float(row.get("timestamp_sec", 0.0))
		timestamp_ms = int(round(timestamp_sec * 1000.0))
	else:
		timestamp_ms = int(timestamp_ms_raw)

	out: dict[str, Any] = {
		"page": int(row.get("page", fallback_page or 0)),
		"frame_name": str(row.get("frame_name", "")),
		"timestamp_ms": timestamp_ms,
		"timestamp_sec": round(timestamp_ms / 1000.0, 3),
	}
	if row.get("frame_index") is not None:
		out["frame_index"] = int(row["frame_index"])
	return out


def load_run_manifest(run_dir: Path) -> dict[str, Any]:
	manifest_path = run_dir / "manifest.json"
	if not manifest_path.exists():
		return {}
	return _read_json(manifest_path)


def load_run_slides(run_dir: Path) -> list[dict[str, Any]]:
	slides_path = run_dir / "artifacts" / "slides.json"
	if not slides_path.exists():
		raise FileNotFoundError(f"slides.json not found: {slides_path}")
	slides_data = _read_json(slides_path)
	slides = slides_data.get("slides", [])
	if not isinstance(slides, list):
		raise ValueError(f"invalid slides payload in {slides_path}")
	return [normalize_slide_row(row, fallback_page=index) for index, row in enumerate(slides, start=1)]


def source_run_id_for_run(run_dir: Path, manifest: dict[str, Any] | None = None) -> str:
	payload = manifest if manifest is not None else load_run_manifest(run_dir)
	metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
	download = metadata.get("download", {}) if isinstance(metadata, dict) else {}
	src_run = download.get("src_run") if isinstance(download, dict) else None
	if isinstance(src_run, str) and src_run:
		return src_run
	return run_dir.name


def build_benchmark_from_run(
	run_dir: Path,
	benchmark_id: str | None = None,
	video_profile: str | None = None,
	tolerance_ms: int = 3000,
	notes: str | None = None,
) -> dict[str, Any]:
	manifest = load_run_manifest(run_dir)
	slides = load_run_slides(run_dir)
	resolved_benchmark_id = benchmark_id or run_dir.name

	payload: dict[str, Any] = {
		"schema_version": 2,
		"benchmark_id": resolved_benchmark_id,
		"approved_run_id": run_dir.name,
		"source_run_id": source_run_id_for_run(run_dir, manifest),
		"source_url": manifest.get("url") if isinstance(manifest.get("url"), str) else None,
		"expected_pages": len(slides),
		"tolerance_ms": int(tolerance_ms),
		"pages": slides,
	}
	if video_profile:
		payload["video_profile"] = video_profile
	if notes:
		payload["notes"] = notes
	return payload


def write_benchmark(
	benchmark_id: str,
	payload: dict[str, Any],
	benchmarks_dir: Path = BENCHMARKS_DIR,
) -> Path:
	out_path = benchmarks_dir / benchmark_id / "expected_pages.json"
	_write_json(out_path, payload)
	return out_path


def load_benchmark(
	benchmark_id: str,
	benchmarks_dir: Path = BENCHMARKS_DIR,
) -> dict[str, Any] | None:
	benchmark_path = benchmarks_dir / benchmark_id / "expected_pages.json"
	if not benchmark_path.exists():
		return None
	return _read_json(benchmark_path)


def resolve_benchmark_id_for_run(
	run_dir: Path,
	benchmark_id: str | None = None,
	benchmarks_dir: Path = BENCHMARKS_DIR,
) -> tuple[str | None, str | None]:
	if benchmark_id:
		if (benchmarks_dir / benchmark_id / "expected_pages.json").exists():
			return benchmark_id, None
		return None, f"benchmark not found: {benchmark_id}"

	manifest = load_run_manifest(run_dir)
	metadata = manifest.get("metadata", {}) if isinstance(manifest, dict) else {}

	# Priority 1: benchmark id already recorded in run metadata.
	bench_eval = metadata.get("benchmark_eval", {}) if isinstance(metadata, dict) else {}
	hinted_benchmark = bench_eval.get("benchmark_id") if isinstance(bench_eval, dict) else None
	if isinstance(hinted_benchmark, str) and hinted_benchmark:
		if (benchmarks_dir / hinted_benchmark / "expected_pages.json").exists():
			return hinted_benchmark, None

	# Priority 2: benchmark named after current run id.
	if (benchmarks_dir / run_dir.name / "expected_pages.json").exists():
		return run_dir.name, None

	# Priority 3: source_run benchmark for reuse-frames runs.
	src_run = source_run_id_for_run(run_dir, manifest)
	if src_run != run_dir.name and (benchmarks_dir / src_run / "expected_pages.json").exists():
		return src_run, None

	# Priority 4 (fallback): resolve by unique source_url match.
	source_url = manifest.get("url") if isinstance(manifest.get("url"), str) else None
	if source_url and benchmarks_dir.exists():
		url_matches: list[str] = []
		for bench_dir in sorted(benchmarks_dir.iterdir()):
			if not bench_dir.is_dir():
				continue
			bench = load_benchmark(bench_dir.name, benchmarks_dir=benchmarks_dir)
			if bench and bench.get("source_url") == source_url:
				url_matches.append(bench_dir.name)
		if len(url_matches) == 1:
			return url_matches[0], None
		if len(url_matches) > 1:
			return None, f"multiple benchmarks matched source_url {source_url}: {', '.join(url_matches)}"

	return None, "no benchmark matched this run"


def _align_pages(
	expected_pages: list[dict[str, Any]],
	actual_pages: list[dict[str, Any]],
	tolerance_ms: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
	matches: list[dict[str, Any]] = []
	missing: list[dict[str, Any]] = []
	extra: list[dict[str, Any]] = []
	expected_index = 0
	actual_index = 0

	while expected_index < len(expected_pages) and actual_index < len(actual_pages):
		expected = expected_pages[expected_index]
		actual = actual_pages[actual_index]
		delta_ms = int(actual["timestamp_ms"]) - int(expected["timestamp_ms"])
		if abs(delta_ms) <= tolerance_ms:
			matches.append({
				"expected_page": int(expected["page"]),
				"actual_page": int(actual["page"]),
				"expected_frame_name": expected.get("frame_name"),
				"actual_frame_name": actual.get("frame_name"),
				"expected_timestamp_ms": int(expected["timestamp_ms"]),
				"actual_timestamp_ms": int(actual["timestamp_ms"]),
				"delta_ms": delta_ms,
			})
			expected_index += 1
			actual_index += 1
		elif delta_ms < -tolerance_ms:
			extra.append(actual)
			actual_index += 1
		else:
			missing.append(expected)
			expected_index += 1

	if expected_index < len(expected_pages):
		missing.extend(expected_pages[expected_index:])
	if actual_index < len(actual_pages):
		extra.extend(actual_pages[actual_index:])
	return matches, missing, extra


def evaluate_slides_against_benchmark(
	actual_pages: list[dict[str, Any]],
	benchmark: dict[str, Any],
	max_miss_rate: float = 0.15,
	max_excess_rate: float = 0.20,
) -> dict[str, Any]:
	expected_pages_raw = benchmark.get("pages")
	expected_pages: list[dict[str, Any]] = []
	if isinstance(expected_pages_raw, list):
		expected_pages = [normalize_slide_row(row, fallback_page=index) for index, row in enumerate(expected_pages_raw, start=1)]

	expected_count_raw = benchmark.get("expected_pages")
	expected_count = int(expected_count_raw) if expected_count_raw is not None else len(expected_pages)
	page_count = len(actual_pages)

	count_miss_rate = None
	count_excess_rate = None
	if expected_count > 0:
		count_miss_rate = round(max(0.0, (expected_count - page_count) / float(expected_count)), 6)
		count_excess_rate = round(max(0.0, (page_count - expected_count) / float(expected_count)), 6)

	report: dict[str, Any] = {
		"benchmark_id": benchmark.get("benchmark_id"),
		"page_count": page_count,
		"expected_pages": expected_count if expected_count > 0 else None,
		"count_miss_rate": count_miss_rate,
		"count_excess_rate": count_excess_rate,
		"gate_max_miss_rate": max_miss_rate,
		"gate_max_excess_rate": max_excess_rate,
	}

	if not expected_pages:
		if expected_count <= 0:
			report.update({
				"comparison_mode": "missing-pages",
				"matched_pages": None,
				"precision": None,
				"recall": None,
				"f1": None,
				"miss_rate": None,
				"excess_rate": None,
				"missing_count": None,
				"extra_count": None,
				"missing_pages": [],
				"extra_pages": [],
				"matches": [],
				"tolerance_ms": benchmark.get("tolerance_ms"),
				"gate": "unknown",
				"gate_pass": False,
				"reason": "benchmark has no expected page data",
			})
			return report

		miss_rate = round(max(0.0, (expected_count - page_count) / float(expected_count)), 6)
		excess_rate = round(max(0.0, (page_count - expected_count) / float(expected_count)), 6)
		gate_pass = miss_rate <= max_miss_rate and excess_rate <= max_excess_rate and page_count > 0
		report.update({
			"comparison_mode": "count-only",
			"matched_pages": None,
			"precision": None,
			"recall": None,
			"f1": None,
			"miss_rate": miss_rate,
			"excess_rate": excess_rate,
			"missing_count": None,
			"extra_count": None,
			"missing_pages": [],
			"extra_pages": [],
			"matches": [],
			"tolerance_ms": benchmark.get("tolerance_ms"),
			"gate": "pass" if gate_pass else "fail",
			"gate_pass": gate_pass,
			"reason": None,
		})
		return report

	tolerance_ms = int(benchmark.get("tolerance_ms", 3000))
	matches, missing_pages, extra_pages = _align_pages(expected_pages, actual_pages, tolerance_ms)
	matched_pages = len(matches)
	missing_count = len(missing_pages)
	extra_count = len(extra_pages)
	precision = round(matched_pages / float(page_count), 6) if page_count > 0 else 0.0
	recall = round(matched_pages / float(expected_count), 6) if expected_count > 0 else 0.0
	f1 = 0.0
	if precision + recall > 0.0:
		f1 = round((2.0 * precision * recall) / (precision + recall), 6)

	miss_rate = round(missing_count / float(expected_count), 6) if expected_count > 0 else 0.0
	excess_rate = round(extra_count / float(expected_count), 6) if expected_count > 0 else 0.0
	gate_pass = miss_rate <= max_miss_rate and excess_rate <= max_excess_rate and page_count > 0
	abs_deltas = [abs(int(match["delta_ms"])) for match in matches]

	report.update({
		"comparison_mode": "page-aligned",
		"matched_pages": matched_pages,
		"precision": precision,
		"recall": recall,
		"f1": f1,
		"miss_rate": miss_rate,
		"excess_rate": excess_rate,
		"missing_count": missing_count,
		"extra_count": extra_count,
		"missing_pages": missing_pages,
		"extra_pages": extra_pages,
		"matches": matches,
		"tolerance_ms": tolerance_ms,
		"avg_abs_delta_ms": round(sum(abs_deltas) / len(abs_deltas), 2) if abs_deltas else None,
		"max_abs_delta_ms": max(abs_deltas) if abs_deltas else None,
		"gate": "pass" if gate_pass else "fail",
		"gate_pass": gate_pass,
		"reason": None,
	})
	return report


def evaluate_run_directory(
	run_dir: Path,
	benchmark_id: str | None = None,
	benchmarks_dir: Path = BENCHMARKS_DIR,
) -> dict[str, Any]:
	actual_pages = load_run_slides(run_dir)
	resolved_benchmark_id, reason = resolve_benchmark_id_for_run(
		run_dir,
		benchmark_id=benchmark_id,
		benchmarks_dir=benchmarks_dir,
	)
	if resolved_benchmark_id is None:
		return {
			"run_id": run_dir.name,
			"benchmark_id": benchmark_id,
			"comparison_mode": "missing-benchmark",
			"page_count": len(actual_pages),
			"expected_pages": None,
			"matched_pages": None,
			"precision": None,
			"recall": None,
			"f1": None,
			"miss_rate": None,
			"excess_rate": None,
			"count_miss_rate": None,
			"count_excess_rate": None,
			"missing_count": None,
			"extra_count": None,
			"missing_pages": [],
			"extra_pages": [],
			"matches": [],
			"tolerance_ms": None,
			"gate": "unknown",
			"gate_pass": False,
			"gate_max_miss_rate": 0.15,
			"gate_max_excess_rate": 0.20,
			"reason": reason,
		}

	benchmark = load_benchmark(resolved_benchmark_id, benchmarks_dir=benchmarks_dir)
	if benchmark is None:
		return {
			"run_id": run_dir.name,
			"benchmark_id": resolved_benchmark_id,
			"comparison_mode": "missing-benchmark",
			"page_count": len(actual_pages),
			"expected_pages": None,
			"matched_pages": None,
			"precision": None,
			"recall": None,
			"f1": None,
			"miss_rate": None,
			"excess_rate": None,
			"count_miss_rate": None,
			"count_excess_rate": None,
			"missing_count": None,
			"extra_count": None,
			"missing_pages": [],
			"extra_pages": [],
			"matches": [],
			"tolerance_ms": None,
			"gate": "unknown",
			"gate_pass": False,
			"gate_max_miss_rate": 0.15,
			"gate_max_excess_rate": 0.20,
			"reason": f"benchmark not found: {resolved_benchmark_id}",
		}

	report = evaluate_slides_against_benchmark(actual_pages, benchmark)
	report["run_id"] = run_dir.name
	report["benchmark_id"] = resolved_benchmark_id
	report["source_url"] = benchmark.get("source_url")
	return report


def write_benchmark_evaluation(path: Path, report: dict[str, Any]) -> None:
	_write_json(path, report)


def write_benchmark_evaluation_markdown(path: Path, report: dict[str, Any]) -> None:
	lines = [
		"# Benchmark Evaluation",
		"",
		f"- gate: {report.get('gate', 'unknown')}",
		f"- gate_pass: {report.get('gate_pass')}",
		f"- comparison_mode: {report.get('comparison_mode')}",
		f"- run_id: {report.get('run_id')}",
		f"- benchmark_id: {report.get('benchmark_id')}",
		f"- page_count: {report.get('page_count')}",
		f"- expected_pages: {report.get('expected_pages')}",
		f"- matched_pages: {report.get('matched_pages')}",
		f"- precision: {report.get('precision')}",
		f"- recall: {report.get('recall')}",
		f"- f1: {report.get('f1')}",
		f"- miss_rate: {report.get('miss_rate')}",
		f"- excess_rate: {report.get('excess_rate')}",
		f"- count_miss_rate: {report.get('count_miss_rate')}",
		f"- count_excess_rate: {report.get('count_excess_rate')}",
		f"- tolerance_ms: {report.get('tolerance_ms')}",
		f"- reason: {report.get('reason')}",
	]

	missing_pages = report.get("missing_pages")
	if isinstance(missing_pages, list) and missing_pages:
		lines.extend(["", "## Missing Pages"])
		for row in missing_pages[:10]:
			lines.append(f"- p{row.get('page')} at {row.get('timestamp_sec')}s ({row.get('frame_name')})")

	extra_pages = report.get("extra_pages")
	if isinstance(extra_pages, list) and extra_pages:
		lines.extend(["", "## Extra Pages"])
		for row in extra_pages[:10]:
			lines.append(f"- p{row.get('page')} at {row.get('timestamp_sec')}s ({row.get('frame_name')})")

	path.write_text("\n".join(lines) + "\n", encoding="utf-8")
