# YouTube Slides MVP

Day 1 implementation scaffold for extracting webinar slides into PDF artifacts.

## Features in this baseline

- CLI entrypoint with task lifecycle state updates
- Task directory bootstrap (`video`, `frames_raw`, `frames_norm`, `artifacts`, `pdf`)
- `manifest.json` writer with status transitions
- Frame extraction (`ffmpeg`) and frame timestamp manifest generation
- Automatic preprocessing masks for subtitle/progress/speaker/watermark noise
- Multi-stage dedupe pipeline (A/B adjacent, C transition, D fade, E progressive lookback, F chain, G motion-ratio)
- OCR signal report + suspect window detection
- Scene-driven re-extraction windows (always) + OCR-driven windows (when OCR enabled)
- Post-processing: gap refill (novelty + FSM), page completion, FSM collapse, close-pair cleanup
- Three PDF outputs: `slides.pdf`, `slides_with_index.pdf`, `slides_raw.pdf`
- Quality gate: `miss_rate`, `excess_rate`, `compression_ratio` (requires `--expected-pages`)
- Block-feature sidecar for training data collection (Card 4.2)
- Pair classifier integration with threshold fallback (Card 4.3)
- Docker image with required system tools (`yt-dlp`, `ffmpeg`, `python3`)
- Healthcheck command printing dependency versions


## 安装与环境准备

### 1. 安装系统依赖

#### macOS
在项目根目录下运行：
```bash
bash scripts/install_deps_mac.sh
```
如需预览将安装哪些依赖，可加 `--dry-run`。

#### Linux (以 Ubuntu/Debian 为例)
需手动安装依赖：
```bash
sudo apt update
sudo apt install -y python3 python3-pip ffmpeg tesseract-ocr
pip3 install -r requirements.txt
```
如需 `yt-dlp`，可用：
```bash
pip3 install yt-dlp
# 或
sudo apt install yt-dlp
```

### 2. 安装 Python 依赖

建议使用虚拟环境：
```bash
python3 -m venv .venv
source .venv/bin/activate
```
然后安装依赖：
```bash
pip install -r requirements.txt
```

### 3. 健康检查

```bash
make health
# 或
python -m youtube_slides_mvp.cli healthcheck
```

### 4. 快速验证

```bash
make smoke
# 或
make run URL="https://www.youtube.com/watch?v=..." OUTDIR="./runs"
```

---

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
make smoke URL="https://www.youtube.com/watch?v=..." OUTDIR="./runs" FPS=1.0 RETRIES=2 SKIP_OCR=1
make run URL="https://www.youtube.com/watch?v=..." OUTDIR="./runs" FPS=1.0 RETRIES=2 OCR_LANG="eng+chi_sim"
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

Key optional flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | `1.0` | Frame extraction rate (frames/sec) |
| `--expected-pages N` | none | Enable `miss_rate`/`excess_rate` quality gate |
| `--complete-mode` | `iterative` | Page completion: `iterative` or `single-pass` |
| `--gap-refill-mode` | `confidence` | Gap refill after completion: `confidence` (required) |
| `--skip-ocr` | off | Skip OCR stage (scene-driven refill still runs) |
| `--refill-multiplier` | `2.5` | D7 re-extraction FPS multiplier |
| `--max-refill-windows` | `0` | Max suspect windows to re-extract (`0` disables D7 refill) |


## PDF Page Editing

### Installation

1. **本地开发环境安装**（推荐，支持命令行直接调用）：

```bash
# 进入项目根目录
pip install .
# 或者开发模式安装（自动追踪源码变动）
pip install -e .
```

2. **依赖要求**：需已安装 Python 3.10+，并确保 requirements.txt 依赖已装好（如 PyMuPDF/fitz）。

3. **安装后，命令行可直接使用 `pdfpages`：**

```bash
pdfpages slides.pdf --delete 2,5-8,12 -o slides-1.pdf --from slides_raw.pdf
pdfpages slides.pdf --insert 5,7-9,13 --after 3 -o slides-1.pdf --from slides_raw.pdf
pdfpages slides.pdf --replace 3,7=4,8 -o slides-1.pdf --from slides_raw.pdf
pdfpages slides.pdf --delete 2,5-8,12 --insert 5,7-9,13 --after 3 --replace 3,7=4,8 -o slides-1.pdf --from slides_raw.pdf
pdfpages slides.pdf --insert 2 --after 1 --insert 4-5 --after 3 -o slides-1.pdf --from slides_raw.pdf
pdfpages slides.pdf --insert 2,@00:12:34,4-5 --after 17 -o slides-1.pdf --from-run runs/<task>
pdfpages slides.pdf --replace 12,13=4,@754.5s -o slides-1.pdf --from-run runs/<task>
pdfpages slides.pdf --delete 2 --insert 4-5 --after 3 --replace 7=8 -o out.pdf --from slides_raw.pdf --dry-run --verbose
```

如未安装到全局，可用如下方式临时调用：

```bash
PYTHONPATH=src python -m youtube_slides_mvp.pdfpages_cli slides.pdf --delete 2,5-8,12 -o slides-1.pdf --from slides_raw.pdf
```

`--insert` 可以重复出现，每一条都必须紧跟一个 `--after`，例如 `--insert 2 --after 1 --insert 4-5 --after 3`。
`--insert` 和 `--replace` 的 source 侧现在也支持 `@时间` 语法，并且可以和页码 token 混写，例如 `2,@00:12:34,4-5` 或 `1,@754.5s`。`--replace` 使用 `TARGET=SOURCE`，因此不需要额外引号；例如 `12,13=4,@754.5s`。两边展开后的页数必须一致。`--from-run` 可以直接给 `runs/<task>/` 目录，CLI 会自动找到源 PDF 和时间索引；如果不传 `--from-run`，它会从当前 input PDF 所在目录向上查找同样的 run 上下文。
`pdfpages` 采用“先构建编辑计划，再执行渲染”的模型：所有页码都先按原始输入 PDF 解析，再一次性写出结果。写文件时使用临时文件替换（原子写入），减少中断时输出损坏风险。
默认会尽最大努力保留输入 PDF 的 metadata 与 TOC（书签）：指向被删除页的 TOC 条目会被移除，其余条目会重映射到新页码。可通过 `--verbose` 或 `--debug` 查看计划与执行日志。

### Range syntax

- `3` means page 3.
- `3-7` means pages 3 through 7.
- `3,5,7` means pages 3, 5, and 7.
- `5-` means page 5 through the last page.
- `-5` means the first 5 pages.
- `1,3-5,8-` combines forms.
- `last` or `-1` means the last page.

组合操作时，所有页码都按原始输入 PDF 解释，不会随着前一个操作的输出重新编号。`--delete` 和 `--replace` 直接命中原始页号，`--insert --after N` 里的 `N` 也是原始页边界。

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
- `runs/<task_id>/pdf/slides.pdf`             ← selected slides only
- `runs/<task_id>/pdf/slides_with_index.pdf`  ← index page(s) + slides + timestamp links
- `runs/<task_id>/pdf/slides_raw.pdf`         ← all extracted frames (no dedup)
- `runs/<task_id>/manifest.json`

## Evaluation

`pdfpages` 采用“先构建编辑计划，再执行渲染”的模型：所有页码都先按原始输入 PDF 解析，再一次性写出结果。写文件时使用临时文件替换（原子写入），减少中断时输出损坏风险。
默认会尽最大努力保留输入 PDF 的 metadata 与 TOC（书签）：指向被删除页的 TOC 条目会被移除，其余条目会重映射到新页码。可通过 `--verbose` 或 `--debug` 查看计划与执行日志。
python scripts/create_benchmark.py slide-20260409-022438 slide-20260409-022438

# Compare a run against the approved benchmark:
python scripts/eval_run.py slide-20260409-HHMMSS

# Re-run D3-D10 on existing frames with different settings:
python scripts/rerun_d3_d10.py slide-20260409-022438 iterative confidence
```

`eval_run.py` writes `artifacts/benchmark_eval.json` and `artifacts/benchmark_eval.md` so later regressions can be checked automatically.


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
- `runs/<task_id>/artifacts/benchmark_eval.json`
- `runs/<task_id>/artifacts/benchmark_eval.md`
- `runs/<task_id>/artifacts/quality_report.json`
- `runs/<task_id>/artifacts/quality_report.md`
- `runs/<task_id>/pdf/`
- `runs/<task_id>/pdf/slides.pdf`
- `runs/<task_id>/pdf/slides_with_index.pdf`
- `runs/<task_id>/manifest.json`
