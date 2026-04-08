from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

try:
    import pytesseract
except Exception:  # pragma: no cover
    pytesseract = None


@dataclass
class OcrSignal:
    frame_name: str
    text_len: int
    fingerprint: str


def _fingerprint(text: str) -> str:
    return " ".join(text.lower().split())[:160]


def run_ocr_signals(frame_paths: list[Path], lang: str = "eng+chi_sim") -> list[OcrSignal]:
    signals: list[OcrSignal] = []
    for frame in frame_paths:
        if pytesseract is None:
            text = ""
        else:
            try:
                text = pytesseract.image_to_string(Image.open(frame), lang=lang)
            except Exception:
                text = ""
        fp = _fingerprint(text)
        signals.append(OcrSignal(frame_name=frame.name, text_len=len(fp), fingerprint=fp))
    return signals


def detect_suspect_windows(
    selected_rows: list[dict[str, int | float | str]],
    signals: list[OcrSignal],
    stale_run_threshold: int = 6,
    empty_run_threshold: int = 10,
    empty_run_min_span_sec: float = 20.0,
) -> list[dict[str, int | float | str]]:
    windows: list[dict[str, int | float | str]] = []
    by_name = {s.frame_name: s for s in signals}

    stale = 0
    last_fp = None
    start_row = None
    empty_count = 0
    empty_start = None

    for row in selected_rows:
        name = str(row["frame_name"])
        sig = by_name.get(name)
        cur_fp = sig.fingerprint if sig else ""

        if cur_fp == last_fp and cur_fp != "":
            stale += 1
            if start_row is None:
                start_row = row
        else:
            if stale >= stale_run_threshold and start_row is not None:
                windows.append(
                    {
                        "start_ts": start_row["timestamp_sec"],
                        "end_ts": row["timestamp_sec"],
                        "reason": "ocr-stale-run",
                        "stale_count": stale,
                    }
                )
            stale = 0
            start_row = None
        last_fp = cur_fp

        # Fallback path: OCR cannot read text (empty fingerprints) for too long.
        if cur_fp == "":
            empty_count += 1
            if empty_start is None:
                empty_start = row
        else:
            if empty_count >= empty_run_threshold and empty_start is not None:
                span = float(row["timestamp_sec"]) - float(empty_start["timestamp_sec"])
                if span >= empty_run_min_span_sec:
                    windows.append(
                        {
                            "start_ts": empty_start["timestamp_sec"],
                            "end_ts": row["timestamp_sec"],
                            "reason": "ocr-empty-run",
                            "empty_count": empty_count,
                        }
                    )
            empty_count = 0
            empty_start = None

    if selected_rows and empty_count >= empty_run_threshold and empty_start is not None:
        last_row = selected_rows[-1]
        span = float(last_row["timestamp_sec"]) - float(empty_start["timestamp_sec"])
        if span >= empty_run_min_span_sec:
            windows.append(
                {
                    "start_ts": empty_start["timestamp_sec"],
                    "end_ts": last_row["timestamp_sec"],
                    "reason": "ocr-empty-run",
                    "empty_count": empty_count,
                }
            )

    return windows


def write_ocr_report(path: Path, signals: list[OcrSignal], windows: list[dict[str, int | float | str]]) -> None:
    payload = {
        "ocr_available": pytesseract is not None,
        "signal_count": len(signals),
        "suspect_windows": windows,
        "signals": [
            {"frame_name": s.frame_name, "text_len": s.text_len, "fingerprint": s.fingerprint}
            for s in signals
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
