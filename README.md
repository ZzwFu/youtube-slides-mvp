# YouTube Slides MVP

Day 1 implementation scaffold for extracting webinar slides into PDF artifacts.

## Features in this baseline

- CLI entrypoint with task lifecycle state updates
- Task directory bootstrap (`video`, `frames_raw`, `frames_norm`, `artifacts`, `pdf`)
- `manifest.json` writer with status transitions
- Frame extraction (`ffmpeg`) and frame timestamp manifest generation
- Automatic preprocessing masks for subtitle/progress/speaker/watermark noise
- Multi-stage dedupe pipeline (adjacent, reveal, transition, final pass)
- OCR signal report + suspect window detection
- Dual PDF output (`slides.pdf`, `slides_with_index.pdf`) + quality gate reports
- Docker image with required system tools (`yt-dlp`, `ffmpeg`, `python3`)
- Healthcheck command printing dependency versions

## Quick start

```bash
cd /Users/victor/.openclaw/workspace/projects/youtube-slides-mvp
make deps
make health
make smoke
```

## Make targets

```bash
make dry-deps  # preview host installs
make deps      # install host + python deps
make health    # dependency healthcheck
make smoke     # no-download smoke run
make run       # full pipeline run (download->preprocess->dedupe->pdf->qa)
```

Optional variables:

```bash
make smoke URL="https://www.youtube.com/watch?v=..." OUTDIR="./runs" FPS=2.0 RETRIES=2 SKIP_OCR=1
make run URL="https://www.youtube.com/watch?v=..." OUTDIR="./runs" FPS=2.0 RETRIES=2 OCR_LANG="eng+chi_sim"
make run URL="https://www.youtube.com/watch?v=..." MASK_CONFIG="./mask.json"
make run URL="https://www.youtube.com/watch?v=..." REFILL_MULTIPLIER=3.0 MAX_REFILL_WINDOWS=4 REFILL_WINDOW_CAP_SEC=60
```

## Install host tools (macOS)

```bash
cd /Users/victor/.openclaw/workspace/projects/youtube-slides-mvp
bash scripts/install_deps_mac.sh
# preview only:
bash scripts/install_deps_mac.sh --dry-run
```

## CLI

```bash
PYTHONPATH=src python -m youtube_slides_mvp.cli healthcheck
PYTHONPATH=src python -m youtube_slides_mvp.cli run --url <youtube_url> --outdir ./runs
```

## Output layout

Each run creates:

- `runs/<task_id>/video/`
- `runs/<task_id>/frames_raw/`
- `runs/<task_id>/frames_norm/`
- `runs/<task_id>/artifacts/`
- `runs/<task_id>/artifacts/frame_manifest.json`
- `runs/<task_id>/artifacts/mask_profile.json`
- `runs/<task_id>/artifacts/ocr_report.json`
- `runs/<task_id>/artifacts/slides.json`
- `runs/<task_id>/artifacts/quality_report.json`
- `runs/<task_id>/artifacts/quality_report.md`
- `runs/<task_id>/pdf/`
- `runs/<task_id>/pdf/slides.pdf`
- `runs/<task_id>/pdf/slides_with_index.pdf`
- `runs/<task_id>/manifest.json`
