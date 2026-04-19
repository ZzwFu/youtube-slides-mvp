from __future__ import annotations

from pathlib import Path

import fitz

from src.youtube_slides_mvp.extract import write_frame_manifest
from src.youtube_slides_mvp.pdfpages import build_edit_plan, expand_page_spec
from src.youtube_slides_mvp.pdfpages_cli import main


def _make_pdf(
    path: Path,
    labels: list[str],
    *,
    toc: list[list[int | str]] | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    try:
        for label in labels:
            page = doc.new_page(width=300, height=200)
            page.insert_text((24, 96), label, fontsize=18)

        if toc:
            doc.set_toc(toc)
        if metadata:
            doc.set_metadata(metadata)

        doc.save(str(path))
    finally:
        doc.close()


def _read_pdf_texts(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [page.get_text("text").strip() for page in doc]
    finally:
        doc.close()


def _make_run_context(run_dir: Path, labels: list[str], timestamps: list[float]) -> Path:
    (run_dir / "pdf").mkdir(parents=True, exist_ok=True)
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    source_pdf = run_dir / "pdf" / "slides_raw.pdf"
    _make_pdf(source_pdf, labels)

    frame_rows = [
        {
            "frame_index": idx,
            "frame_name": f"frame_{idx:06d}.jpg",
            "timestamp_sec": round(ts, 6),
            "timestamp_ms": int(round(ts * 1000)),
        }
        for idx, ts in enumerate(timestamps, start=1)
    ]
    write_frame_manifest(run_dir / "artifacts" / "frame_manifest.json", fps=1.0, frame_rows=frame_rows)
    (run_dir / "manifest.json").write_text("{}\n", encoding="utf-8")
    return source_pdf


def test_expand_page_spec_supports_flexible_ranges() -> None:
    assert expand_page_spec("3", 10) == [3]
    assert expand_page_spec("3-7", 10) == [3, 4, 5, 6, 7]
    assert expand_page_spec("3,5,7", 10) == [3, 5, 7]
    assert expand_page_spec("5-", 10) == [5, 6, 7, 8, 9, 10]
    assert expand_page_spec("-5", 10) == [1, 2, 3, 4, 5]
    assert expand_page_spec("1,3-5,8-", 10) == [1, 3, 4, 5, 8, 9, 10]
    assert expand_page_spec("last", 10) == [10]
    assert expand_page_spec("-1", 10) == [10]


def test_build_edit_plan_stays_in_original_page_coordinates() -> None:
    plan = build_edit_plan(
        input_page_count=6,
        source_page_count=8,
        source_rows=None,
        delete_spec="2,5",
        insert_ops=[("3,4", 1), ("6", 4)],
        replace_spec="3,6=1,8",
    )

    assert plan.delete_pages == {2, 5}
    assert plan.replacement_map == {3: 1, 6: 8}
    assert plan.insert_groups == {1: [[3, 4]], 4: [[6]]}
    assert plan.output_page_count == 7


def test_pdfpages_delete(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 7)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 4)])

    exit_code = main([str(input_pdf), "--delete", "2,5-6", "-o", str(output_pdf), "--from", str(source_pdf)])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == ["input 1", "input 3", "input 4"]


def test_pdfpages_insert(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 5)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 6)])

    exit_code = main([
        str(input_pdf),
        "--insert",
        "2,4-5",
        "--after",
        "2",
        "-o",
        str(output_pdf),
        "--from",
        str(source_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "input 2",
        "source 2",
        "source 4",
        "source 5",
        "input 3",
        "input 4",
    ]


def test_pdfpages_multiple_insert_pairs_are_all_applied(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 5)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 6)])

    exit_code = main([
        str(input_pdf),
        "--insert",
        "2",
        "--after",
        "1",
        "--insert",
        "4-5",
        "--after",
        "3",
        "-o",
        str(output_pdf),
        "--from",
        str(source_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "source 2",
        "input 2",
        "input 3",
        "source 4",
        "source 5",
        "input 4",
    ]


def test_pdfpages_replace(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 9)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 9)])

    exit_code = main([
        str(input_pdf),
        "--replace",
        "3,7=4,8",
        "-o",
        str(output_pdf),
        "--from",
        str(source_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "input 2",
        "source 4",
        "input 4",
        "input 5",
        "input 6",
        "source 8",
        "input 8",
    ]


def test_pdfpages_mixed_source_insert_falls_back_to_input_pdf_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-001"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 4)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 6)], [0.0, 1.0, 2.0, 3.0, 4.0])

    exit_code = main([
        str(input_pdf),
        "--insert",
        "2,@1.2,4-5",
        "--after",
        "1",
        "-o",
        str(output_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "source 2",
        "source 2",
        "source 4",
        "source 5",
        "input 2",
        "input 3",
    ]


def test_pdfpages_mixed_source_replace_can_use_from_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-002"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 6)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 5)], [0.0, 1.0, 2.0, 3.0])

    exit_code = main([
        str(input_pdf),
        "--replace",
        "2,4=1,@1.2",
        "-o",
        str(output_pdf),
        "--from-run",
        str(run_dir),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == ["input 1", "source 1", "input 3", "source 2", "input 5"]


def test_pdfpages_legacy_colon_replace_still_uses_input_pdf_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-005"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 6)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 5)], [0.0, 1.0, 2.0, 3.0])

    exit_code = main([
        str(input_pdf),
        "--replace",
        "2,4:1,@1.2",
        "-o",
        str(output_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == ["input 1", "source 1", "input 3", "source 2", "input 5"]


def test_pdfpages_rejects_replace_length_mismatch(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-004"
    input_pdf = tmp_path / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 5)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 5)], [0.0, 1.0, 2.0, 3.0])

    try:
        main([
            str(input_pdf),
            "--replace",
            "2=1,@1.2",
            "-o",
            str(output_pdf),
            "--from-run",
            str(run_dir),
        ])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected replace length mismatch to fail")


def test_pdfpages_mixed_source_specs_work_in_combined_commands(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-003"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 7)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 6)], [0.0, 1.0, 2.0, 3.0, 4.0])

    exit_code = main([
        str(input_pdf),
        "--insert",
        "2,@1.2",
        "--after",
        "1",
        "--replace",
        "3,5=1,@1.2",
        "-o",
        str(output_pdf),
        "--from-run",
        str(run_dir),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "source 2",
        "source 2",
        "input 2",
        "source 1",
        "input 4",
        "source 2",
        "input 6",
    ]


def test_pdfpages_combined_operations_use_original_page_numbers(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 7)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 7)])

    exit_code = main([
        str(input_pdf),
        "--delete",
        "2,5",
        "--insert",
        "2",
        "--after",
        "3",
        "--replace",
        "4=4",
        "-o",
        str(output_pdf),
        "--from",
        str(source_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "input 3",
        "source 2",
        "source 4",
        "input 6",
    ]


def test_pdfpages_rejects_delete_replace_overlap(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 5)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 5)])

    try:
        main([
            str(input_pdf),
            "--delete",
            "3",
            "--replace",
            "3=1",
            "-o",
            str(output_pdf),
            "--from",
            str(source_pdf),
        ])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected combined delete/replace conflict to fail")


def test_pdfpages_dry_run_prints_plan_and_skips_output_write(tmp_path: Path, capsys) -> None:
    input_pdf = tmp_path / "slides.pdf"
    source_pdf = tmp_path / "slides_raw.pdf"
    output_pdf = tmp_path / "slides_out.pdf"
    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 5)])
    _make_pdf(source_pdf, [f"source {idx}" for idx in range(1, 5)])

    exit_code = main([
        str(input_pdf),
        "--delete",
        "2",
        "--insert",
        "1,2",
        "--after",
        "1",
        "-o",
        str(output_pdf),
        "--from",
        str(source_pdf),
        "--dry-run",
    ])

    assert exit_code == 0
    assert not output_pdf.exists()
    assert "planned output page count: 5" in capsys.readouterr().out


def test_pdfpages_preserves_metadata_and_remaps_toc_after_delete(tmp_path: Path) -> None:
    input_pdf = tmp_path / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(
        input_pdf,
        [f"input {idx}" for idx in range(1, 4)],
        toc=[[1, "Intro", 1], [1, "Conclusion", 3]],
        metadata={"title": "Demo Deck", "author": "qa"},
    )

    exit_code = main([
        str(input_pdf),
        "--delete",
        "2",
        "-o",
        str(output_pdf),
    ])

    assert exit_code == 0

    doc = fitz.open(str(output_pdf))
    try:
        assert doc.metadata.get("title") == "Demo Deck"
        assert doc.get_toc(simple=True) == [[1, "Intro", 1], [1, "Conclusion", 2]]
    finally:
        doc.close()