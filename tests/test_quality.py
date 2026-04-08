from src.youtube_slides_mvp.quality import compute_quality_metrics, evaluate_gate


def test_quality_gate_pass() -> None:
    metrics = compute_quality_metrics(raw_count=100, selected_count=20, suspect_windows=1)
    out = evaluate_gate(metrics, max_duplicate_rate=0.9, max_suspect_windows=3)
    assert out["gate_pass"] is True
