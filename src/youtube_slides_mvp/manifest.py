from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .models import TaskManifest, TaskPaths


def make_task_id(prefix: str = "task") -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"


def build_task_paths(outdir: Path, task_id: str) -> TaskPaths:
    task_dir = outdir / task_id
    return TaskPaths(
        task_dir=task_dir,
        video_dir=task_dir / "video",
        frames_raw_dir=task_dir / "frames_raw",
        frames_norm_dir=task_dir / "frames_norm",
        artifacts_dir=task_dir / "artifacts",
        pdf_dir=task_dir / "pdf",
        manifest_path=task_dir / "manifest.json",
    )


def ensure_task_dirs(paths: TaskPaths) -> None:
    for p in [
        paths.task_dir,
        paths.video_dir,
        paths.frames_raw_dir,
        paths.frames_norm_dir,
        paths.artifacts_dir,
        paths.pdf_dir,
    ]:
        p.mkdir(parents=True, exist_ok=True)


def write_manifest(manifest: TaskManifest, manifest_path: Path) -> None:
    manifest_path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
