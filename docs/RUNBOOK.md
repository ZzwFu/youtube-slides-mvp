# YouTube Slides MVP Runbook

## Daily operation

1. `make health`
2. `make run URL="<youtube-url>" OUTDIR="./runs" FPS=1.0 RETRIES=2`
3. Open latest task `manifest.json` and verify `metadata.quality.gate_pass=true`
4. Deliver three PDFs in `pdf/`:
   - `slides.pdf` — selected slides only
   - `slides_with_index.pdf` — index page(s) with timestamp links + slides
   - `slides_raw.pdf` — all extracted frames before dedup (for audit)

## Quality gate fields

After Phase 1, the gate uses three metrics (requires `--expected-pages N`):

| Field | Meaning | Pass threshold |
|-------|---------|----------------|
| `miss_rate` | `(expected - selected) / expected` (0 if selected ≥ expected) | ≤ 0.15 |
| `excess_rate` | `(selected - expected) / expected` (0 if selected ≤ expected) | ≤ 0.20 |
| `compression_ratio` | `(raw - selected) / raw` | info only |
| `gate` | `pass` / `fail` / `unknown` | — |

When `--expected-pages` is not provided, gate is `unknown` and `gate_pass=false`.

## Failure triage

1. **Download fails**
   - Check `metadata.download.message`
   - Increase `RETRIES`
   - Retry with lower fps if needed

2. **Extraction fails**
   - Check ffmpeg availability via `make health`
   - Inspect source video in `video/`

3. **OCR noisy**
   - Run with `SKIP_OCR=1` for emergency output (scene-driven refill still runs)
   - Tune `OCR_LANG`

4. **Quality gate fails (miss_rate high)**
   - Inspect `artifacts/quality_report.md`
   - Re-run via `rerun_d3_d10.py` with `gap_refill_mode=confidence`
   - Increase `REFILL_MULTIPLIER` or `MAX_REFILL_WINDOWS`

5. **Quality gate fails (excess_rate high / duplicates)**
   - Inspect `artifacts/ocr_report.json` suspect windows
   - Check p13/14 and p38/39 intervals in slides_with_index.pdf
   - Re-run with `--complete-mode single-pass` to reduce over-completion

## Evaluation

```bash
# One-time benchmark creation from a manually approved run:
python scripts/create_benchmark.py slide-20260409-022438 slide-20260409-022438

# Compare a finished run against the approved benchmark:
python scripts/eval_run.py slide-20260409-HHMMSS

# Supply explicit benchmark if source_run differs:
python scripts/eval_run.py slide-20260409-HHMMSS slide-20260409-022438
```

`eval_run.py` refreshes `artifacts/benchmark_eval.json` and `artifacts/benchmark_eval.md` in the evaluated run directory.

Exit code 0 = gate pass, 1 = gate fail or benchmark missing, 2 = usage error.

## Re-run D3-D10 on existing frames

```bash
python scripts/rerun_d3_d10.py <source_run_id> [complete_mode] [gap_refill_mode]
# Examples:
python scripts/rerun_d3_d10.py slide-20260409-022438 iterative confidence
```

`gap_refill_mode` is confidence-only.

Outputs `runs/<new_id>/artifacts/experiment_log.json` with page_count and quality metrics.
If a benchmark exists for `<source_run_id>`, the rerun also writes `benchmark_eval.json` and `benchmark_eval.md` automatically.

## Training the pair classifier (Card 4.3)

Once you have multiple runs with sidecar data:

```bash
# Collect sidecar data during rerun:
python scripts/rerun_d3_d10.py slide-20260409-022438 iterative confidence
# (edit rerun script to pass sidecar_path to dedupe_frames)

# Train:
python scripts/train_classifier.py --sidecar "runs/*/artifacts/sidecar.json"
# Model saved to models/pair_classifier.pkl
# dedupe_frames auto-loads it on next run
```

## Deliverables checklist

- `manifest.json`
- `artifacts/frame_manifest.json`
- `artifacts/slides.json`
- `artifacts/benchmark_eval.json`
- `artifacts/benchmark_eval.md`
- `artifacts/quality_report.json`
- `pdf/slides.pdf`
- `pdf/slides_with_index.pdf`
- `pdf/slides_raw.pdf`
