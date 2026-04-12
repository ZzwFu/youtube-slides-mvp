from src.youtube_slides_mvp.quality import compute_quality_metrics, evaluate_gate


def test_quality_unknown_without_expected() -> None:
    metrics = compute_quality_metrics(raw_count=3600, selected_count=40, suspect_windows=1)
    assert metrics["miss_rate"] == -1.0
    assert metrics["excess_rate"] == -1.0
    assert metrics["expected_pages"] is None
    out = evaluate_gate(metrics)
    assert out["gate"] == "unknown"
    assert out["gate_pass"] is False


def test_quality_gate_pass() -> None:
    # 70 selected vs 68 expected: slight excess (2/68 ≈ 2.9%) — within 20% limit
    metrics = compute_quality_metrics(raw_count=3600, selected_count=70, suspect_windows=2, expected_pages=68)
    out = evaluate_gate(metrics)
    assert out["gate"] == "pass"
    assert out["gate_pass"] is True
    assert float(out["miss_rate"]) == 0.0
    assert float(out["excess_rate"]) > 0.0


def test_quality_gate_fail_miss() -> None:
    # 50 selected vs 68 expected: miss_rate = (68-50)/68 ≈ 0.265 > 0.15
    metrics = compute_quality_metrics(raw_count=3600, selected_count=50, suspect_windows=2, expected_pages=68)
    out = evaluate_gate(metrics)
    assert out["gate"] == "fail"
    assert out["gate_pass"] is False
    assert float(out["miss_rate"]) > 0.15


def test_quality_gate_fail_excess() -> None:
    # 90 selected vs 68 expected: excess_rate = (90-68)/68 ≈ 0.324 > 0.20
    metrics = compute_quality_metrics(raw_count=3600, selected_count=90, suspect_windows=2, expected_pages=68)
    out = evaluate_gate(metrics)
    assert out["gate"] == "fail"
    assert out["gate_pass"] is False
    assert float(out["excess_rate"]) > 0.20


def test_quality_compression_ratio() -> None:
    metrics = compute_quality_metrics(raw_count=3600, selected_count=68, suspect_windows=0, expected_pages=68)
    assert abs(float(metrics["compression_ratio"]) - (3600 - 68) / 3600) < 1e-4
    assert metrics["miss_rate"] == 0.0
    assert metrics["excess_rate"] == 0.0
