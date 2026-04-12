# Handoff Notes

## Pipeline version

- pipeline_version: `v0.5-phase4` — Phases 1–4 of REMEDIATION_PLAN.md complete
- thresholds_version: frozen DedupeConfig defaults (see `dedupe.py`)

## Main entrypoints

- CLI: `src/youtube_slides_mvp/cli.py`
- Make commands: `Makefile`
- Runbook: `docs/RUNBOOK.md`
- Remediation plan: `docs/REMEDIATION_PLAN.md`

## Implemented stages

| Stage | Description | Status |
|-------|-------------|--------|
| D3 | Preprocess frames (mask, normalize) | ✅ |
| D4/D5 | Multi-stage dedupe A-G | ✅ |
| D6 | OCR signals + suspect window detection | ✅ |
| D7 | Scene-driven + OCR-driven re-extraction and merge | ✅ |
| D8 | Render: `slides.pdf`, `slides_with_index.pdf`, `slides_raw.pdf` | ✅ |
| D9 | Quality gate: miss_rate, excess_rate, compression_ratio | ✅ |
| D10 | Post-processing: gap refill → page completion → FSM collapse → close-pair cleanup | ✅ |

## Known limitations

- OCR depends on local tesseract runtime; falls back to empty text if unavailable.
- `--skip-ocr` skips OCR-driven refill windows but scene-driven windows always run.
- Index PDF links target YouTube timestamps only (no internal PDF page jumps).
- Pair classifier (Card 4.3) requires manual sidecar collection + training before activation.
- `eval_run.py` compares only total page count (not per-page timestamp precision).

## Recommended next steps

1. Collect sidecar data across 5+ benchmark runs, train pair classifier, verify F1 > 0.95.
2. Add per-page timestamp annotation to `expected_pages.json` for precision/recall eval.
3. Dynamic mask detection by scene regions (Card 5.2 FrameCache is a prerequisite).
4. Add `--expected-pages` to Makefile variables for gate to activate by default.
