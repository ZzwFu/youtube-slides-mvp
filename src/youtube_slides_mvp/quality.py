from __future__ import annotations

import json
from pathlib import Path


def compute_quality_metrics(
    raw_count: int,
    selected_count: int,
    suspect_windows: int,
    expected_pages: int | None = None,
) -> dict[str, float | int | bool | str | None]:
    compression_ratio = 0.0
    if raw_count > 0:
        compression_ratio = max(0.0, (raw_count - selected_count) / float(raw_count))

    miss_rate = -1.0
    excess_rate = -1.0
    if expected_pages is not None and expected_pages > 0:
        miss_rate = max(0.0, (expected_pages - selected_count) / float(expected_pages))
        excess_rate = max(0.0, (selected_count - expected_pages) / float(expected_pages))

    return {
        "raw_count": raw_count,
        "selected_count": selected_count,
        "expected_pages": expected_pages,
        "compression_ratio": round(compression_ratio, 6),
        "miss_rate": round(miss_rate, 6),
        "excess_rate": round(excess_rate, 6),
        "suspect_windows": suspect_windows,
    }


def evaluate_gate(
    metrics: dict[str, float | int | bool | str | None],
    max_miss_rate: float = 0.15,
    max_excess_rate: float = 0.20,
    max_suspect_windows: int = 8,
) -> dict[str, float | int | bool | str | None]:
    expected_pages = metrics.get("expected_pages")
    miss_rate = float(metrics["miss_rate"])
    excess_rate = float(metrics["excess_rate"])

    if expected_pages is None:
        gate = "unknown"
        gate_pass = False
    else:
        gate_pass = bool(
            miss_rate <= max_miss_rate
            and excess_rate <= max_excess_rate
            and int(metrics["suspect_windows"]) <= max_suspect_windows
            and int(metrics["selected_count"]) > 0
        )
        gate = "pass" if gate_pass else "fail"

    out = dict(metrics)
    out["gate"] = gate
    out["gate_pass"] = gate_pass
    out["gate_max_miss_rate"] = max_miss_rate
    out["gate_max_excess_rate"] = max_excess_rate
    out["gate_max_suspect_windows"] = max_suspect_windows
    return out


def write_quality_report(path: Path, payload: dict[str, float | int | bool | str | None]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def write_quality_markdown(path: Path, payload: dict[str, float | int | bool | str | None]) -> None:
    lines = [
        "# Quality Report",
        "",
        f"- gate: {payload.get('gate', 'unknown')}",
        f"- gate_pass: {payload.get('gate_pass')}",
        f"- raw_count: {payload.get('raw_count')}",
        f"- selected_count: {payload.get('selected_count')}",
        f"- expected_pages: {payload.get('expected_pages')}",
        f"- compression_ratio: {payload.get('compression_ratio')}",
        f"- miss_rate: {payload.get('miss_rate')}",
        f"- excess_rate: {payload.get('excess_rate')}",
        f"- suspect_windows: {payload.get('suspect_windows')}",
        f"- gate_max_miss_rate: {payload.get('gate_max_miss_rate')}",
        f"- gate_max_excess_rate: {payload.get('gate_max_excess_rate')}",
        f"- gate_max_suspect_windows: {payload.get('gate_max_suspect_windows')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
