#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
fi

run_cmd() {
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "[DRY-RUN] $*"
  else
    echo "[RUN] $*"
    "$@"
  fi
}

need_tool() {
  local tool="$1"
  if command -v "$tool" >/dev/null 2>&1; then
    echo "[OK] $tool already installed"
    return 1
  fi
  echo "[MISS] $tool not found"
  return 0
}

if ! command -v brew >/dev/null 2>&1; then
  echo "ERROR: Homebrew not found. Install Homebrew first: https://brew.sh"
  exit 1
fi

missing=0
if need_tool yt-dlp; then
  run_cmd brew install yt-dlp
  missing=1
fi

if need_tool ffmpeg; then
  run_cmd brew install ffmpeg
  missing=1
fi

if need_tool tesseract; then
  run_cmd brew install tesseract
  missing=1
fi

if [[ "$missing" -eq 0 ]]; then
  echo "All required tools already present"
fi

echo "\nVersions:"
if command -v yt-dlp >/dev/null 2>&1; then
  yt-dlp --version || true
fi
if command -v ffmpeg >/dev/null 2>&1; then
  ffmpeg -version | head -n 1 || true
fi
if command -v tesseract >/dev/null 2>&1; then
  tesseract --version | head -n 1 || true
fi
