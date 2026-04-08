# YouTube Slides MVP Runbook

## Daily operation

1. `make health`
2. `make run URL="<youtube-url>" OUTDIR="./runs" FPS=2.0 RETRIES=2`
3. Open latest task `manifest.json` and verify `metadata.quality.gate_pass=true`
4. Deliver two PDFs in `pdf/`.

## Failure triage

1. Download fails
- Check `metadata.download.message`
- Increase `RETRIES`
- Retry with lower fps if needed

2. Extraction fails
- Check ffmpeg availability via `make health`
- Inspect source video in `video/`

3. OCR noisy
- Run with `SKIP_OCR=1` for emergency output
- Tune `OCR_LANG`

4. Quality gate fails
- Inspect `artifacts/quality_report.md`
- Inspect `artifacts/ocr_report.json` suspect windows
- Re-run with adjusted fps

## Deliverables checklist

- `manifest.json`
- `artifacts/frame_manifest.json`
- `artifacts/slides.json`
- `artifacts/quality_report.json`
- `pdf/slides.pdf`
- `pdf/slides_with_index.pdf`
