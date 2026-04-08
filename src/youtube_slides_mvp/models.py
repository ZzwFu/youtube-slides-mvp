from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class TaskStatus(str, Enum):
    CREATED = "created"
    DOWNLOADING = "downloading"
    EXTRACTING = "extracting"
    PREPROCESSING = "preprocessing"
    DEDUPING = "deduping"
    RENDERING = "rendering"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TaskEvent:
    status: TaskStatus
    ts: str
    message: str


@dataclass
class TaskManifest:
    task_id: str
    url: str
    outdir: str
    task_dir: str
    pipeline_version: str = "v1.0-d10-scaffold"
    thresholds_version: str = "unset"
    status: TaskStatus = TaskStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[TaskEvent] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "url": self.url,
            "outdir": self.outdir,
            "task_dir": self.task_dir,
            "pipeline_version": self.pipeline_version,
            "thresholds_version": self.thresholds_version,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
            "events": [
                {"status": ev.status.value, "ts": ev.ts, "message": ev.message}
                for ev in self.events
            ],
        }

    def transition(self, status: TaskStatus, message: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.status = status
        self.updated_at = now
        self.events.append(TaskEvent(status=status, ts=now, message=message))


@dataclass
class TaskPaths:
    task_dir: Path
    video_dir: Path
    frames_raw_dir: Path
    frames_norm_dir: Path
    artifacts_dir: Path
    pdf_dir: Path
    manifest_path: Path
