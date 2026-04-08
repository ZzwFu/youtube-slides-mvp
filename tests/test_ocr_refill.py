from src.youtube_slides_mvp.ocr_refill import OcrSignal, detect_suspect_windows


def test_detect_suspect_windows_empty_run_fallback() -> None:
    rows = []
    for i in range(15):
        rows.append({"frame_name": f"frame_{i:06d}.jpg", "timestamp_sec": float(i * 3)})
    signals = [OcrSignal(frame_name=r["frame_name"], text_len=0, fingerprint="") for r in rows]

    windows = detect_suspect_windows(rows, signals, empty_run_threshold=10, empty_run_min_span_sec=20.0)
    assert windows
    assert windows[0]["reason"] == "ocr-empty-run"
