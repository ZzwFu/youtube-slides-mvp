from __future__ import annotations

import json
from pathlib import Path


def compute_quality_metrics(raw_count: int, selected_count: int, suspect_windows: int) -> dict[str, float | int | bool]:
    duplicate_rate = 0.0
    if raw_count > 0:
        duplicate_rate = max(0.0, (raw_count - selected_count) / float(raw_count))

    completeness = 0.0
    if raw_count > 0:
        completeness = min(1.0, selected_count / float(raw_count))

    return {
        "raw_count": raw_count,
        "selected_count": selected_count,
        "duplicate_rate": round(duplicate_rate, 6),
        "completeness": round(completeness, 6),
        "suspect_windows": suspect_windows,
    }


def evaluate_gate(metrics: dict[str, float | int | bool], max_duplicate_rate: float = 0.98, max_suspect_windows: int = 8) -> dict[str, float | int | bool]:
    gate_pass = bool(
        float(metrics["duplicate_rate"]) <= max_duplicate_rate
        and int(metrics["suspect_windows"]) <= max_suspect_windows
        and int(metrics["selected_count"]) > 0
    )
    out = dict(metrics)
    out["gate_pass"] = gate_pass
    out["gate_max_duplicate_rate"] = max_duplicate_rate
    out["gate_max_suspect_windows"] = max_suspect_windows
    return out


def write_quality_report(path: Path, payload: dict[str, float | int | bool]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def write_quality_markdown(path: Path, payload: dict[str, float | int | bool]) -> None:
    lines = [
        "# Quality Report",
        "",
        f"- gate_pass: {payload.get('gate_pass')}",
        f"- raw_count: {payload.get('raw_count')}",
        f"- selected_count: {payload.get('selected_count')}",
        f"- duplicate_rate: {payload.get('duplicate_rate')}",
        f"- completeness: {payload.get('completeness')}",
        f"- suspect_windows: {payload.get('suspect_windows')}",
        f"- gate_max_duplicate_rate: {payload.get('gate_max_duplicate_rate')}",
        f"- gate_max_suspect_windows: {payload.get('gate_max_suspect_windows')}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
