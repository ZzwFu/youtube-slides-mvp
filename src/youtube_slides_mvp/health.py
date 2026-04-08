from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class ToolVersion:
    name: str
    found: bool
    version: str


def _cmd_version(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return out or err or "unknown"


def detect_tools() -> list[ToolVersion]:
    checks = {
        "python": [sys.executable, "--version"],
        "yt-dlp": ["yt-dlp", "--version"],
        "ffmpeg": ["ffmpeg", "-version"],
    }

    versions: list[ToolVersion] = []
    for tool, cmd in checks.items():
        executable = cmd[0]
        if shutil.which(executable) is None and executable != sys.executable:
            versions.append(ToolVersion(name=tool, found=False, version="missing"))
            continue
        versions.append(ToolVersion(name=tool, found=True, version=_cmd_version(cmd).splitlines()[0]))
    return versions


def run_healthcheck() -> int:
    versions = detect_tools()
    missing = [v for v in versions if not v.found]

    for version in versions:
        status = "OK" if version.found else "MISSING"
        print(f"[{status}] {version.name}: {version.version}")

    return 1 if missing else 0
