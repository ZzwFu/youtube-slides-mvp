from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Sequence
from pathlib import Path

from .pdfpages import _split_replace_spec, edit_pdf_pages


def _configure_logging(verbose: bool, debug: bool) -> None:
    if not verbose and not debug:
        return

    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _consume_value(tokens: Sequence[str], index: int, option_name: str) -> str:
    if index >= len(tokens):
        raise ValueError(f"{option_name} requires a value")
    value = tokens[index]
    if value.startswith("--"):
        raise ValueError(f"{option_name} requires a value")
    return value


def _parse_edit_tokens(tokens: Sequence[str]) -> tuple[str | None, list[tuple[str, int]], str | None]:
    delete_spec: str | None = None
    replace_spec: str | None = None
    insert_ops: list[tuple[str, int]] = []
    pending_insert: str | None = None

    index = 0
    while index < len(tokens):
        token = tokens[index]

        if token == "--insert":
            if pending_insert is not None:
                raise ValueError("--insert must be followed immediately by --after before another edit option")
            pending_insert = _consume_value(tokens, index + 1, "--insert")
            index += 2
            continue

        if token == "--after":
            if pending_insert is None:
                raise ValueError("--after must immediately follow --insert")
            after_raw = _consume_value(tokens, index + 1, "--after")
            try:
                after = int(after_raw)
            except ValueError as exc:  # noqa: BLE001
                raise ValueError("--after must be an integer") from exc
            insert_ops.append((pending_insert, after))
            pending_insert = None
            index += 2
            continue

        if pending_insert is not None:
            raise ValueError("--insert must be followed immediately by --after")

        if token == "--delete":
            if delete_spec is not None:
                raise ValueError("--delete may only be given once")
            delete_spec = _consume_value(tokens, index + 1, "--delete")
            index += 2
            continue

        if token == "--replace":
            if replace_spec is not None:
                raise ValueError("--replace may only be given once")
            replace_spec = _consume_value(tokens, index + 1, "--replace")
            index += 2
            continue

        raise ValueError(f"unexpected argument: {token}")

    if pending_insert is not None:
        raise ValueError("--insert must be followed immediately by --after")

    return delete_spec, insert_ops, replace_spec


def _uses_time_source_specs(insert_ops: list[tuple[str, int]], replace_spec: str | None) -> bool:
    if any("@" in insert_spec for insert_spec, _ in insert_ops):
        return True
    if replace_spec is None:
        return False
    _, _, source_spec = _split_replace_spec(replace_spec)
    return "@" in source_spec


def _load_source_rows(index_path: Path) -> list[dict[str, int | float | str]]:
    if not index_path.is_file():
        raise ValueError(f"source index not found: {index_path}")

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"unsupported source index format: {index_path}")

    rows = payload.get("frames")
    if rows is None:
        rows = payload.get("slides")
    if not isinstance(rows, list):
        raise ValueError(f"unsupported source index format: {index_path}")

    normalized: list[dict[str, int | float | str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"unsupported source index row in {index_path}")
        normalized.append(dict(row))

    return normalized


def _find_run_root_from_context(input_pdf: Path) -> Path | None:
    resolved_input = input_pdf.resolve()
    for candidate in resolved_input.parents:
        if not candidate.is_dir():
            continue

        manifest_path = candidate / "manifest.json"
        raw_pdf = candidate / "pdf" / "slides_raw.pdf"
        raw_index = candidate / "artifacts" / "frame_manifest.json"
        if manifest_path.is_file() and raw_pdf.is_file() and raw_index.is_file():
            return candidate

        slides_pdf = candidate / "pdf" / "slides.pdf"
        slides_index = candidate / "artifacts" / "slides.json"
        if manifest_path.is_file() and slides_pdf.is_file() and slides_index.is_file():
            return candidate

    return None


def _resolve_run_source_context(
    run_root: Path,
    source_pdf: Path | None = None,
) -> tuple[Path, list[dict[str, int | float | str]]]:
    raw_pdf = run_root / "pdf" / "slides_raw.pdf"
    raw_index = run_root / "artifacts" / "frame_manifest.json"
    slides_pdf = run_root / "pdf" / "slides.pdf"
    slides_index = run_root / "artifacts" / "slides.json"

    if source_pdf is None:
        if raw_pdf.is_file() and raw_index.is_file():
            return raw_pdf, _load_source_rows(raw_index)
        if slides_pdf.is_file() and slides_index.is_file():
            return slides_pdf, _load_source_rows(slides_index)
        raise ValueError(f"unable to resolve a source PDF and index under run directory: {run_root}")

    if source_pdf.name == "slides_raw.pdf":
        if not raw_index.is_file():
            raise ValueError(f"missing frame manifest for {source_pdf.name} under run directory: {run_root}")
        return source_pdf, _load_source_rows(raw_index)

    if source_pdf.name == "slides.pdf":
        if not slides_index.is_file():
            raise ValueError(f"missing slide index for {source_pdf.name} under run directory: {run_root}")
        return source_pdf, _load_source_rows(slides_index)

    raise ValueError("time-based source specs require a source PDF named slides_raw.pdf or slides.pdf")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfpages",
        description=(
            "Flexible PDF page editing: delete, insert, and replace can be combined in a single command. "
            "Page specs stay numeric, and source specs may mix page tokens with @timestamp tokens to reference source pages by video time. "
            "All target page numbers and insert positions are interpreted against the original input PDF (not renumbered after edits). "
            "Replace specs use TARGET=SOURCE so they can be passed without shell quotes, and both sides must expand to the same number of pages. "
            "Use --dry-run to validate and preview output page count without writing a file.\n\n"
            "Multiple --insert operations are supported: each --insert <pages> must be immediately followed by --after <N>. "
            "When time-based source specs are used, the CLI can load the source PDF and its index from --from-run or by walking up from the input PDF directory."
        ),
        epilog=(
            "\nExamples:\n"
            "  pdfpages runs/<task>/pdf/slides.pdf --insert 2,@00:12:34,4-5 --after 17 -o out.pdf\n"
            "  pdfpages input.pdf --replace 12,13=4,@754.5s -o out.pdf --from-run runs/<task>\n"
            "  pdfpages input.pdf --delete 2,5-8 --insert 5,@00:12:34,7-9 --after 3 --replace 3,7=4,8 -o out.pdf --from slides_raw.pdf\n"
            "\nTime syntax examples:\n"
            "  @754.5s\n"
            "  @12:34\n"
            "  @01:02:03.500\n"
            "  @12:34-@12:50\n"
            "\nIf --from-run is omitted, the CLI looks for a run layout in the input PDF's parent directories.\n"
            "Use --verbose (or --debug) for planning/execution logs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_pdf", type=Path, help="input PDF to modify")

    parser.add_argument(
        "--from",
        dest="source_pdf",
        type=Path,
        help="source PDF for insert/replace; optional when time-based source specs are resolved from --from-run or local run context",
    )
    parser.add_argument(
        "--from-run",
        dest="source_run",
        type=Path,
        help="run directory (for example runs/<task>) used to auto-locate the source PDF and time index",
    )
    parser.add_argument("-o", "--output", required=True, type=Path, help="output PDF path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and plan edits without writing the output PDF",
    )
    parser.add_argument("--verbose", action="store_true", help="print summary logs")
    parser.add_argument("--debug", action="store_true", help="print detailed planning logs")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, edit_tokens = parser.parse_known_args(argv)
    _configure_logging(args.verbose, args.debug)

    try:
        if not edit_tokens:
            parser.error("at least one of --delete, --insert, or --replace is required")

        delete_spec, insert_ops, replace_spec = _parse_edit_tokens(edit_tokens)

        source_pdf = args.source_pdf
        source_rows: list[dict[str, int | float | str]] | None = None
        uses_time_specs = _uses_time_source_specs(insert_ops, replace_spec)

        if uses_time_specs:
            run_root = args.source_run or _find_run_root_from_context(args.input_pdf)
            if run_root is None:
                parser.error("time-based source specs require --from-run or a PDF inside a run directory")
            source_pdf, source_rows = _resolve_run_source_context(run_root, source_pdf)
        elif (insert_ops or replace_spec is not None) and source_pdf is None:
            if args.source_run is not None:
                source_pdf, _ = _resolve_run_source_context(args.source_run, None)
            else:
                parser.error("--from is required with --insert or --replace")

        output_pages = edit_pdf_pages(
            args.input_pdf,
            args.output,
            source_pdf=source_pdf,
            source_rows=source_rows,
            delete_spec=delete_spec,
            insert_ops=insert_ops,
            replace_spec=replace_spec,
            dry_run=args.dry_run,
        )

        if args.dry_run:
            print(f"[DRY-RUN] planned output page count: {output_pages}")
        return 0
    except ValueError as exc:
        parser.error(str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())