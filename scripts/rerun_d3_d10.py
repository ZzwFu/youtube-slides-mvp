"""
Reuse extracted frames from a previous run and execute D3-D10 directly.
Usage: python scripts/rerun_d3_d10.py [source_run_id] [complete_mode]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


def main() -> int:
    src_id = sys.argv[1] if len(sys.argv) > 1 else "slide-20260408-034253"
    complete_mode = sys.argv[2] if len(sys.argv) > 2 else "iterative"
    if complete_mode not in {"iterative", "single-pass"}:
        print(f"ERROR: complete_mode must be iterative or single-pass, got: {complete_mode}")
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
    manifest = TaskManifest(task_id=tid, url=URL, outdir=str(RUNS_DIR), task_dir=str(paths.task_dir))
    manifest.metadata["download"] = {"mode": "reuse-frames", "src_run": src_id, "ok": True}
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
    selected_orig, selected_rows, rescued_gap = _cli._rescue_gap_pages(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=paths.frames_raw_dir,
    )
    print(f"  Rescued gap pages: {rescued_gap}")

    selected_orig, selected_rows, completed_pages = _cli._complete_pages(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
        frame_rows=frame_rows,
        frames_raw_dir=paths.frames_raw_dir,
        mode=complete_mode,
    )
    print(f"  Completed pages: {completed_pages}  mode={complete_mode}")

    selected_orig, selected_rows, fsm_collapsed, dropped_blank = _cli._postprocess_additive_state_machine(
        selected_orig=selected_orig,
        selected_rows=selected_rows,
    )
    print(f"  FSM collapsed pages: {fsm_collapsed}")
    print(f"  Dropped blank frames: {dropped_blank}")

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

    render_pdf_b_with_index(selected_orig, selected_rows, source_url=URL, out_pdf=pdf_b)
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

    # ── D9 Quality ───────────────────────────────────────────────────────────
    qmetrics = compute_quality_metrics(
        raw_count=len(raw_frames),
        selected_count=len(selected_orig),
        suspect_windows=0,  # no OCR in this script
    )
    gated = evaluate_gate(qmetrics)
    write_quality_report(paths.artifacts_dir / "quality_report.json", gated)
    write_quality_markdown(paths.artifacts_dir / "quality_report.md", gated)
    manifest.metadata["quality"] = {
        "report_json": str(paths.artifacts_dir / "quality_report.json"),
        "report_md": str(paths.artifacts_dir / "quality_report.md"),
        **gated,
    }
    print(f"  Quality gate: {'PASS' if gated.get('passed', False) else 'FAIL'}")

    manifest.transition(TaskStatus.DONE, "reuse-frames D3-D10 pipeline complete")
    write_manifest(manifest, paths.manifest_path)
    print(f"\nDone!  {RUNS_DIR}/{tid}/pdf/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
