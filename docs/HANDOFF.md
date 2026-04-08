# Handoff Notes

## MVP pipeline versions

- pipeline_version: `v0.2-d2` plus D3-D10 scaffold stages in `cli.py`
- thresholds_version: `unset` (next step: freeze threshold profile per run)

## Main entrypoints

- CLI: `src/youtube_slides_mvp/cli.py`
- Make commands: `Makefile`
- Runbook: `docs/RUNBOOK.md`

## Known limitations

- OCR depends on local tesseract runtime; falls back to empty text if unavailable.
- D7 refill currently reports suspect windows but does not perform window-specific re-extraction yet.
- Index PDF links target YouTube timestamps and do not include internal page jump links.

## Recommended next tuning

1. Add dynamic mask detection by scene regions.
2. Implement true D7 local re-sample and merge.
3. Tighten quality gate thresholds with curated webinar benchmark set.
