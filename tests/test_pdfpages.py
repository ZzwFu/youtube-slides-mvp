from __future__ import annotations

from pathlib import Path

import fitz

from src.youtube_slides_mvp.extract import write_frame_manifest
from src.youtube_slides_mvp.pdfpages import expand_page_spec
from src.youtube_slides_mvp.pdfpages_cli import main


def _make_pdf(path: Path, labels: list[str]) -> None:
    doc = fitz.open()
    try:
        for label in labels:
            page = doc.new_page(width=300, height=200)
            page.insert_text((24, 96), label, fontsize=18)
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
        "3,7:4,8",
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


def test_pdfpages_time_based_insert_falls_back_to_input_pdf_context(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-001"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 4)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 5)], [0.0, 1.0, 2.0, 3.0])

    exit_code = main([
        str(input_pdf),
        "--insert",
        "@1.2-@2.4",
        "--after",
        "1",
        "-o",
        str(output_pdf),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == [
        "input 1",
        "source 2",
        "source 3",
        "input 2",
        "input 3",
    ]


def test_pdfpages_time_based_replace_can_use_from_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "slide-002"
    input_pdf = run_dir / "pdf" / "slides.pdf"
    output_pdf = tmp_path / "slides_out.pdf"

    _make_pdf(input_pdf, [f"input {idx}" for idx in range(1, 4)])
    _make_run_context(run_dir, [f"source {idx}" for idx in range(1, 5)], [0.0, 1.0, 2.0, 3.0])

    exit_code = main([
        str(input_pdf),
        "--replace",
        "2:@1.2",
        "-o",
        str(output_pdf),
        "--from-run",
        str(run_dir),
    ])

    assert exit_code == 0
    assert _read_pdf_texts(output_pdf) == ["input 1", "source 2", "input 3"]


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
        "4:4",
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
            "3:1",
            "-o",
            str(output_pdf),
            "--from",
            str(source_pdf),
        ])
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected combined delete/replace conflict to fail")