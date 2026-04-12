# 综合修复方案 — Opus 4.6 定稿（2026-04-12）

> 综合 GPT 5.4 审计 + Opus 4.6 独立审查，冲突处以 Opus 为准。
> 供 Sonnet 4.6 按 task card 逐项执行。

## 执行原则

1. **每个 task card 独立提交**，commit message 带 card 编号
2. **每次只改一个机制**，改完立即跑回归：`rerun_d3_d10.py slide-20260409-022438 iterative confidence`
3. **回归基线**：68 页（iterative none）无重复 + 73 页（iterative confidence）区间补齐
4. **红线**：p13/14, p38/39 区间不得引入重复；已补齐的 p41→42 四页不得丢失

---

## Phase 1: 快赢修复（3 个独立 task，互不依赖）

### Card 1.1 — 修 quality gate 指标

**文件**: `src/youtube_slides_mvp/quality.py`

**当前问题**: `duplicate_rate` 实际是压缩率，`completeness` 是其 complement，`max_duplicate_rate=0.98` 永远放行。

**改为**:
```python
def compute_quality_metrics(
    raw_count: int,
    selected_count: int,
    suspect_windows: int,
    expected_pages: int | None = None,  # 用户可传入预期页数
) -> dict[str, float | int | bool]:
    compression_ratio = 0.0
    if raw_count > 0:
        compression_ratio = max(0.0, (raw_count - selected_count) / float(raw_count))
    
    # 如果有预期页数，计算真实 miss/dup 估计
    if expected_pages and expected_pages > 0:
        miss_rate = max(0.0, (expected_pages - selected_count) / expected_pages) if selected_count < expected_pages else 0.0
        excess_rate = max(0.0, (selected_count - expected_pages) / expected_pages) if selected_count > expected_pages else 0.0
    else:
        miss_rate = -1.0  # unknown
        excess_rate = -1.0
    
    return {
        "raw_count": raw_count,
        "selected_count": selected_count,
        "compression_ratio": round(compression_ratio, 6),
        "miss_rate": round(miss_rate, 6),
        "excess_rate": round(excess_rate, 6),
        "suspect_windows": suspect_windows,
    }
```

**gate 改为**:
- `miss_rate <= 0.15`（允许 15% 漏页）
- `excess_rate <= 0.20`（允许 20% 多页）
- `selected_count > 0`
- 当 `expected_pages` 未提供时，gate 标记为 `"unknown"`

**CLI 新增参数**: `--expected-pages N`（可选）

**验收**: `pytest tests/test_quality.py` 通过 + 手动跑一次确认 gate 输出合理

---

### Card 1.2 — 解耦 scene-driven refill 和 skip_ocr

**文件**: `src/youtube_slides_mvp/cli.py` run_pipeline 函数内

**当前问题**: L1082 的 `not skip_ocr` 把 scene-driven windows 也拦了

**改法**: 将 refill 大 if 块拆成两个独立块：

```python
# Block A: scene-driven refill (always runs if video exists)
if windows_scene and video_path and video_path.exists() and refill_multiplier > 1.0:
    ...do scene-driven re-extraction...

# Block B: OCR-driven refill (only when OCR enabled)  
if not skip_ocr and windows_ocr and video_path and video_path.exists() and refill_multiplier > 1.0:
    ...do OCR-driven re-extraction...
```

**注意**: 保持 `_merge_windows` 逻辑不变，只是分开触发条件

**验收**: `--skip-ocr` 仍跳过 OCR，但 scene-driven windows 正常触发

---

### Card 1.3 — 修 render OOM + index 截断

**文件**: `src/youtube_slides_mvp/render.py`

**改 render_pdf_a 和 render_pdf_raw**: 用 fitz 逐页 insert_image 替代 Pillow 全量加载

```python
def render_pdf_a(selected_frames: list[Path], out_pdf: Path) -> None:
    if not selected_frames:
        raise ValueError("no selected frames for pdf")
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    for frame_path in selected_frames:
        img = Image.open(frame_path)
        w, h = img.size
        page = doc.new_page(width=w, height=h)
        page.insert_image(fitz.Rect(0, 0, w, h), filename=str(frame_path))
    doc.save(str(out_pdf))
    doc.close()
```

**改 _build_index_page**: 去掉 `items[:40]` 和 `index_rows[:24]` 硬截断，改为多页 index（每页 40 条）

**验收**: 用 3600 帧目录跑 render_pdf_raw 不 OOM；87 页产物 index 完整

---

## Phase 2: 评测基建（依赖 Phase 1 完成）

### Card 2.1 — Golden benchmark + eval 脚本

**新建文件**:
- `benchmarks/slide-20260409-022438/expected_pages.json` — 手工标注 68 页基线的正确页面清单
- `scripts/eval_run.py` — 对比 run 产物与 expected_pages

**expected_pages.json 格式**:
```json
{
  "video_id": "slide-20260409-022438",
  "expected_page_count": 73,
  "pages": [
    {"page": 1, "timestamp_sec": 5.0, "description": "title slide"},
    ...
  ],
  "known_progressive_intervals": [
    {"ts_start": 1040, "ts_end": 1080, "true_pages": 4},
    {"ts_start": 1260, "ts_end": 1290, "true_pages": 1}
  ]
}
```

**eval_run.py 输出**:
```
Precision: 0.96 (70/73 correct)
Recall:    0.96 (70/73 found)
False positives: 3 (progressive-reveal duplicates at ts=[...])
False negatives: 3 (missing pages at ts=[...])
```

**验收**: `eval_run.py slide-20260409-121905` 输出 68/73 recall + 0 FP

---

### Card 2.2 — 实验日志自动化

**改文件**: `scripts/rerun_d3_d10.py`

在脚本末尾自动写 `runs/<id>/experiment_log.json`:
```json
{
  "run_id": "slide-20260409-HHMMSS",
  "base_run": "slide-20260409-022438",
  "complete_mode": "iterative",
  "gap_refill_mode": "confidence",
  "dedupe_config": { ...all 30+ params... },
  "result_pages": 73,
  "diff_vs_baseline": {
    "added_pages": [{"ts": 1056.0, "page": 45}],
    "removed_pages": [],
    "changed_pages": []
  },
  "timestamp": "2026-04-12T14:30:00"
}
```

**验收**: 跑完 rerun 后 `experiment_log.json` 存在且可被 eval_run.py 消费

---

## Phase 3: 后处理链合并（核心架构改造）

### Card 3.1 — 合并 _complete_pages + _postprocess_additive_state_machine

**文件**: `src/youtube_slides_mvp/cli.py`

**根据**: `_complete_pages` 已经实现了"向前看，替换为最完整状态"。`_postprocess_additive_state_machine` 做的是"相邻 additive pair 保留后者"。前者是后者的超集。

**改法**:
1. 在 `_complete_pages` 内部，当选中 replacement 时，同时检查是否形成 additive chain（if 连续多个 candidate 都是前一个的 additive reveal，跳到链尾）
2. 删除 `_postprocess_additive_state_machine` 函数
3. 在 run_pipeline 中去掉对应调用

**验收**: 68 页基线输出不变（diff slides.json = 0）

---

### Card 3.2 — 合并 _rescue_gap_pages + _confidence_refill_pages

**文件**: `src/youtube_slides_mvp/cli.py`

**改法**: 统一为 `_refill_gaps()`，接受 `strategy="novelty"|"fsm_group"` 参数：
- `novelty`: 原 `_rescue_gap_pages` 逻辑（找 gap 中 min_diff 最高的帧）
- `fsm_group`: 原 `_confidence_refill_pages` 逻辑（mini-FSM 分组取尾帧）
- 通用：gap 检测、endpoint pruning、cap 逻辑共享

**验收**: `iterative none` = 68 页不变，`iterative confidence` = 73 页不变

---

### Card 3.3 — 链条从 5 步降到 3 步

合并完成后，pipeline 变为：
```
_refill_gaps(strategy="novelty")     # 原 rescue_gap + confidence_refill
→ _complete_pages()                   # 原 complete + additive FSM
→ _cleanup_close_pairs()              # 不变
```

**验收**: 两种 mode 回归不变

---

## Phase 4: 特征增强（算法路线升级）

### Card 4.1 — 引入 OCR 文本前缀检测

**新建文件**: `src/youtube_slides_mvp/text_compare.py`

**逻辑**: 对相邻/近邻帧对，比较 OCR 文本：
- 如果 text_a 是 text_b 的前缀（忽略尾部空白）→ 确认 progressive-reveal
- 如果 text_a 和 text_b 完全不同 → 确认不同页
- 混合情况 → 交给像素级判定

**集成点**: 在 Stage E 和 `_is_additive` 中作为 **第一优先级** 判定，通过才走像素级

**验收**: 在 p13/14, p38/39 区间确认 OCR 文本不是前缀关系 → 不会误合并

---

### Card 4.2 — Block 级空间特征（48 维）

**改文件**: `src/youtube_slides_mvp/dedupe.py`

**改法**: 新增函数 `_block_features(a, b, grid=(4,4))` → 返回 48 维向量（每个 block 的 diff/neg/pos）

暂时不替换现有 Stage E/F/G，而是**并行输出到 sidecar**：
```json
{"frame_a": "001.jpg", "frame_b": "002.jpg", "block_features": [...48 floats...], "label": "progressive"}
```

这产生训练数据，为 Card 4.3 做准备

**验收**: sidecar JSON 文件存在且特征维度正确

---

### Card 4.3 — 轻量 classifier 替代阈值堆叠

**新建文件**: `scripts/train_classifier.py`

**输入**: Card 4.2 产生的 sidecar + 手工标注的 expected_pages.json
**输出**: `models/pair_classifier.pkl`（scikit-learn GradientBoostingClassifier）

**集成**: 在 Stage E/F 中，如果 model 文件存在则用 classifier 预测，否则 fallback 到阈值

**验收**: 在 benchmark 视频上 F1 > 0.95

---

## Phase 5: 文档与基建收尾

### Card 5.1 — 修复所有过时文档

- README.md: FPS 默认值 1.0（不是 2.0），三份 PDF（不是"dual"）
- RUNBOOK.md: 同上 + 质量门禁字段更新
- HANDOFF.md: D7 已实现 re-extraction，去掉"尚未实现"说法

### Card 5.2 — 提取公共 FrameCache 类

**新建文件**: `src/youtube_slides_mvp/frame_cache.py`

替换 cli.py 内 6 处独立 `_load()` + `cache` dict → 统一 `FrameCache` 实例

---

## 执行顺序建议

```
Phase 1 (1.1 | 1.2 | 1.3 并行) → Phase 2 (2.1 → 2.2) → Phase 3 (3.1 → 3.2 → 3.3) → Phase 4 (4.1 → 4.2 → 4.3) → Phase 5
```

Phase 1 三个 card 完全独立，可以一口气做完。
Phase 2 是后续所有改动的评测基建，必须在 Phase 3/4 之前完成。
Phase 3 是架构改造，风险最高，做完必须全量回归。
Phase 4 是算法升级，可以渐进式引入。
Phase 5 随时可做。
