"""
Reuse extracted frames from a previous run and execute D3-D10 directly.
Usage: python scripts/rerun_d3_d10.py [source_run_id] [complete_mode] [gap_refill_mode=confidence]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from youtube_slides_mvp.benchmark import evaluate_run_directory, write_benchmark_evaluation, write_benchmark_evaluation_markdown
from youtube_slides_mvp.dedupe import DedupeConfig, dedupe_frames
from youtube_slides_mvp.manifest import build_task_paths, ensure_task_dirs, make_task_id, write_manifest
from youtube_slides_mvp.models import TaskManifest, TaskStatus
from youtube_slides_mvp.preprocess import load_mask_profile, preprocess_frames, write_mask_profile
from youtube_slides_mvp.quality import compute_quality_metrics, evaluate_gate, write_quality_markdown, write_quality_report
from youtube_slides_mvp.render import render_pdf_a, render_pdf_b_with_index, render_pdf_raw, write_slides_json

# Import helpers from cli without starting the pipeline
import importlib
_cli = importlib.import_module("youtube_slides_mvp.cli")

RUNS_DIR = Path(__file__).parent.parent / "runs"
URL = "http://youtube.com/watch?v=9eqDWJSvCx4"


def _source_url_for_run(src_run: Path) -> str:
    manifest_path = src_run / "manifest.json"
    if not manifest_path.exists():
        return URL
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return URL
    source_url = payload.get("url")
    if isinstance(source_url, str) and source_url:
        return source_url
    return URL


def main() -> int:
    src_id = sys.argv[1] if len(sys.argv) > 1 else "slide-20260408-034253"
    complete_mode = sys.argv[2] if len(sys.argv) > 2 else "iterative"
    gap_refill_mode = "confidence"
    if len(sys.argv) > 3:
        gap_refill_mode = sys.argv[3].strip().lower()
    if complete_mode not in {"iterative", "single-pass"}:
        print(f"ERROR: complete_mode must be iterative or single-pass, got: {complete_mode}")
        return 2
    if gap_refill_mode != "confidence":
        print(f"ERROR: gap_refill_mode only supports confidence, got: {gap_refill_mode}")
        return 2
    src_run = RUNS_DIR / src_id
    src_frames = src_run / "frames_raw"
    src_manifest = src_run / "artifacts" / "frame_manifest.json"

    if not src_frames.exists():
        print(f"ERROR: {src_frames} not found")
        return 1
    if not src_manifest.exists():
        print(f"ERROR: {src_manifest} not found")
        return 1

    source_url = _source_url_for_run(src_run)

    tid = make_task_id("slide")
    paths = build_task_paths(RUNS_DIR, tid)
    ensure_task_dirs(paths)
    print(f"Task: {tid}")

    # ── Copy frames_raw ──────────────────────────────────────────────────────
    print("Copying frames_raw...")
    src_jpgs = sorted(src_frames.glob("frame_*.jpg"))
    for f in src_jpgs:
        shutil.copy(f, paths.frames_raw_dir / f.name)
    n_frames = len(src_jpgs)
    print(f"  {n_frames} frames copied")

    shutil.copy(src_manifest, paths.artifacts_dir / "frame_manifest.json")

    fps = 1.0
    manifest = TaskManifest(task_id=tid, url=source_url, outdir=str(RUNS_DIR), task_dir=str(paths.task_dir))
    manifest.metadata["download"] = {"mode": "reuse-frames", "src_run": src_id, "source_url": source_url, "ok": True}
    manifest.metadata["extract"] = {"ok": True, "fps": fps, "frame_count": n_frames}

    # ── D3 Preprocess ────────────────────────────────────────────────────────
    manifest.transition(TaskStatus.PREPROCESSING, "D3 preprocess")
    write_manifest(manifest, paths.manifest_path)
    mask_profile = load_mask_profile(None)
    write_mask_profile(paths.artifacts_dir / "mask_profile.json", mask_profile)
    frame_paths = sorted(paths.frames_raw_dir.glob("frame_*.jpg"))
    norm_paths = preprocess_frames(frame_paths, paths.frames_norm_dir, mask_profile)
    manifest.metadata["preprocess"] = {
        "ok": True,
        "input_frames": len(frame_paths),
        "output_frames": len(norm_paths),
    }
    print(f"  Preprocessed {len(norm_paths)} frames")

    # ── D4/D5 Dedupe A-G ────────────────────────────────────────────────────
    manifest.transition(TaskStatus.DEDUPING, "D4/D5 dedupe")
    write_manifest(manifest, paths.manifest_path)
    selected_norm, dedupe_stats = dedupe_frames(norm_paths, DedupeConfig())
    selected_orig = [paths.frames_raw_dir / p.name for p in selected_norm if (paths.frames_raw_dir / p.name).exists()]

    selected_dir = paths.artifacts_dir / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    for src in selected_orig:
        shutil.copy(src, selected_dir / src.name)

    frame_rows_data = json.loads((paths.artifacts_dir / "frame_manifest.json").read_text())
    frame_rows = list(frame_rows_data.get("frames", []))
    selected_rows = _cli._rows_for_selected(selected_orig, frame_rows)
    print(f"  After dedupe A-G: {len(selected_orig)} pages  stats={dedupe_stats}")

    manifest.metadata["dedupe"] = {"ok": True, "stats": dedupe_stats, "selected_count": len(selected_orig)}

    # ── Post-processing ──────────────────────────────────────────────────────
    selected_orig, selected_rows, rescued_gap = _cli._refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=paths.frames_raw_dir,
        strategy="novelty",
        min_gap_sec=15.0,
    )
    print(f"  Rescued gap pages: {rescued_gap}")

    selected_orig, selected_rows, completed_pages, fsm_collapsed, dropped_blank = _cli._complete_pages(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=paths.frames_raw_dir,
        mode=complete_mode,
    )
    print(f"  Completed pages: {completed_pages}  mode={complete_mode}")
    print(f"  FSM collapsed pages: {fsm_collapsed}")
    print(f"  Dropped blank frames: {dropped_blank}")

    selected_orig, selected_rows, confidence_refilled = _cli._refill_gaps(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=paths.frames_raw_dir,
        strategy="fsm_group",
        min_gap_sec=15.0,
        max_rounds=2,
    )
    print(f"  Confidence refilled pages: {confidence_refilled}")

    selected_orig, selected_rows, post_fsm_collapsed = _cli._fsm_collapse(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        fsm_max_diff=0.03,
        fsm_max_neg=0.007,
        fsm_min_dark_cover=0.90,
        fsm_max_dark_add=0.05,
        enable_tier_b=False,
    )
    print(f"  Post-refill FSM collapsed: {post_fsm_collapsed}")

    selected_orig, selected_rows, merged_close_pairs = _cli._cleanup_close_pairs(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
    )
    print(f"  Merged close pairs: {merged_close_pairs}")

    manifest.metadata["dedupe"].update({
        "selected_count": len(selected_orig),
        "dropped_blank_pages": dropped_blank,
        "rescued_gap_pages": rescued_gap,
        "completed_pages": completed_pages,
        "complete_mode": complete_mode,
        "fsm_collapsed_pages": fsm_collapsed,
        "gap_refill_mode": gap_refill_mode,
        "confidence_refilled_pages": confidence_refilled,
        "merged_close_pairs": merged_close_pairs,
    })

    # ── D8 Render ────────────────────────────────────────────────────────────
    manifest.transition(TaskStatus.RENDERING, "D8 render")
    write_manifest(manifest, paths.manifest_path)
    pdf_a = paths.pdf_dir / "slides.pdf"
    pdf_b = paths.pdf_dir / "slides_with_index.pdf"
    pdf_raw = paths.pdf_dir / "slides_raw.pdf"

    render_pdf_a(selected_orig, pdf_a)
    print(f"  slides.pdf              {pdf_a.stat().st_size / 1024 / 1024:.1f} MB  ({len(selected_orig)} pages)")

    render_pdf_b_with_index(selected_orig, selected_rows, source_url=source_url, out_pdf=pdf_b)
    print(f"  slides_with_index.pdf   {pdf_b.stat().st_size / 1024 / 1024:.1f} MB")

    raw_frames = sorted(paths.frames_raw_dir.glob("frame_*.jpg"))
    render_pdf_raw(raw_frames, pdf_raw)
    print(f"  slides_raw.pdf          {pdf_raw.stat().st_size / 1024 / 1024:.1f} MB  ({len(raw_frames)} raw frames)")

    write_slides_json(paths.artifacts_dir / "slides.json", selected_rows)
    manifest.metadata["render"] = {
        "ok": True,
        "pdf_a": str(pdf_a),
        "pdf_b": str(pdf_b),
        "pdf_raw": str(pdf_raw),
        "page_count": len(selected_orig),
        "raw_frame_count": len(raw_frames),
    }

    benchmark_report = evaluate_run_directory(paths.task_dir)
    benchmark_json = paths.artifacts_dir / "benchmark_eval.json"
    benchmark_md = paths.artifacts_dir / "benchmark_eval.md"
    write_benchmark_evaluation(benchmark_json, benchmark_report)
    write_benchmark_evaluation_markdown(benchmark_md, benchmark_report)
    manifest.metadata["benchmark_eval"] = {
        "benchmark_id": benchmark_report.get("benchmark_id"),
        "comparison_mode": benchmark_report.get("comparison_mode"),
        "gate": benchmark_report.get("gate"),
        "gate_pass": benchmark_report.get("gate_pass"),
        "precision": benchmark_report.get("precision"),
        "recall": benchmark_report.get("recall"),
        "f1": benchmark_report.get("f1"),
        "miss_rate": benchmark_report.get("miss_rate"),
        "excess_rate": benchmark_report.get("excess_rate"),
        "missing_count": benchmark_report.get("missing_count"),
        "extra_count": benchmark_report.get("extra_count"),
        "report_json": str(benchmark_json),
        "report_md": str(benchmark_md),
        "reason": benchmark_report.get("reason"),
    }
    print(f"  Benchmark eval: {benchmark_report.get('gate', 'unknown').upper()}  mode={benchmark_report.get('comparison_mode')}")

    # ── D9 Quality ───────────────────────────────────────────────────────────
    qmetrics = compute_quality_metrics(
        raw_count=len(raw_frames),
        selected_count=len(selected_orig),
        suspect_windows=0,  # no OCR in this script
        expected_pages=benchmark_report.get("expected_pages") if benchmark_report.get("expected_pages") is not None else None,
    )
    gated = evaluate_gate(qmetrics)
    write_quality_report(paths.artifacts_dir / "quality_report.json", gated)
    write_quality_markdown(paths.artifacts_dir / "quality_report.md", gated)
    manifest.metadata["quality"] = {
        "report_json": str(paths.artifacts_dir / "quality_report.json"),
        "report_md": str(paths.artifacts_dir / "quality_report.md"),
        **gated,
    }
    print(f"  Quality gate: {'PASS' if gated.get('gate_pass', False) else 'FAIL'}")

    manifest.transition(TaskStatus.DONE, "reuse-frames D3-D10 pipeline complete")
    write_manifest(manifest, paths.manifest_path)

    # ── Experiment log ───────────────────────────────────────────────────────
    experiment_log = {
        "task_id": tid,
        "src_run": src_id,
        "complete_mode": complete_mode,
        "gap_refill_mode": gap_refill_mode,
        "page_count": len(selected_orig),
        "raw_frame_count": len(raw_frames),
        "quality": {k: v for k, v in gated.items()},
        "benchmark_eval": {
            "benchmark_id": benchmark_report.get("benchmark_id"),
            "comparison_mode": benchmark_report.get("comparison_mode"),
            "gate": benchmark_report.get("gate"),
            "precision": benchmark_report.get("precision"),
            "recall": benchmark_report.get("recall"),
            "f1": benchmark_report.get("f1"),
            "miss_rate": benchmark_report.get("miss_rate"),
            "excess_rate": benchmark_report.get("excess_rate"),
        },
        "diff_vs_baseline": {
            "missing_pages": benchmark_report.get("missing_pages", []),
            "extra_pages": benchmark_report.get("extra_pages", []),
        },
    }
    exp_log_path = paths.artifacts_dir / "experiment_log.json"
    exp_log_path.write_text(json.dumps(experiment_log, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(f"  Experiment log: {exp_log_path}")

    print(f"\nDone!  {RUNS_DIR}/{tid}/pdf/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
