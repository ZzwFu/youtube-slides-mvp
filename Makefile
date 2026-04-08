PYTHON ?= /Users/victor/.openclaw/workspace/projects/trading-gui/.venv/bin/python
PYTHONPATH ?= src
URL ?= https://www.youtube.com/watch?v=dQw4w9WgXcQ
OUTDIR ?= ./runs
FPS ?= 1.0
RETRIES ?= 2
OCR_LANG ?= eng+chi_sim
SKIP_OCR ?= 0
MASK_CONFIG ?=
REFILL_MULTIPLIER ?= 2.5
MAX_REFILL_WINDOWS ?= 3
REFILL_WINDOW_CAP_SEC ?= 60

.PHONY: deps health smoke run dry-deps

dry-deps:
	bash scripts/install_deps_mac.sh --dry-run

deps:
	bash scripts/install_deps_mac.sh
	$(PYTHON) -m pip install -r requirements.txt

health:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m youtube_slides_mvp.cli healthcheck

smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m youtube_slides_mvp.cli run --url "$(URL)" --outdir "$(OUTDIR)" --no-download --fps "$(FPS)" --download-retries "$(RETRIES)" --ocr-lang "$(OCR_LANG)" --refill-multiplier "$(REFILL_MULTIPLIER)" --max-refill-windows "$(MAX_REFILL_WINDOWS)" --refill-window-cap-sec "$(REFILL_WINDOW_CAP_SEC)" $(if $(filter 1,$(SKIP_OCR)),--skip-ocr,) $(if $(MASK_CONFIG),--mask-config "$(MASK_CONFIG)",)

run:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m youtube_slides_mvp.cli run --url "$(URL)" --outdir "$(OUTDIR)" --fps "$(FPS)" --download-retries "$(RETRIES)" --ocr-lang "$(OCR_LANG)" --refill-multiplier "$(REFILL_MULTIPLIER)" --max-refill-windows "$(MAX_REFILL_WINDOWS)" --refill-window-cap-sec "$(REFILL_WINDOW_CAP_SEC)" $(if $(filter 1,$(SKIP_OCR)),--skip-ocr,) $(if $(MASK_CONFIG),--mask-config "$(MASK_CONFIG)",)
