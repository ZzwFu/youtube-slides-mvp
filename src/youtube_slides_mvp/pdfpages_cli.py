from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .pdfpages import edit_pdf_pages


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdfpages",
        description=(
            "Flexible PDF page editing: delete, insert, and replace can be combined in a single command. "
            "All page specs and insert positions are interpreted against the original input PDF (not renumbered after edits).\n\n"
            "Multiple --insert operations are supported: each --insert <pages> must be immediately followed by --after <N>. "
            "All insertions are applied in the order given."
        ),
        epilog=(
            "\nUsage patterns for multiple insertions:\n"
            "  pdfpages input.pdf --insert 2 --after 1 --insert 4-5 --after 3 -o out.pdf --from raw.pdf\n"
            "  pdfpages input.pdf --delete 2,5-8 --insert 5,7-9 --after 3 -o out.pdf --from raw.pdf\n"
            "  pdfpages input.pdf --insert 2 --after 1 --insert 4-5 --after 3 --replace 7:8 -o out.pdf --from raw.pdf\n"
            "\nEach --insert <pages> must be paired with a following --after <N>. "
            "All page numbers and after-positions refer to the original input PDF.\n"
            "\nPage spec syntax:\n"
            "  3         # page 3\n"
            "  3-7       # pages 3 through 7\n"
            "  3,5,7     # pages 3, 5, and 7\n"
            "  5-        # page 5 through last\n"
            "  -5        # first 5 pages\n"
            "  last, -1  # last page\n"
            "  1,3-5,8-  # combine forms\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input_pdf", type=Path, help="input PDF to modify")

    parser.add_argument("--from", dest="source_pdf", type=Path, help="source PDF for insert/replace")
    parser.add_argument("-o", "--output", required=True, type=Path, help="output PDF path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args, edit_tokens = parser.parse_known_args(argv)

    try:
        if not edit_tokens:
            parser.error("at least one of --delete, --insert, or --replace is required")

        delete_spec, insert_ops, replace_spec = _parse_edit_tokens(edit_tokens)

        if (insert_ops or replace_spec is not None) and args.source_pdf is None:
            parser.error("--from is required with --insert or --replace")

        edit_pdf_pages(
            args.input_pdf,
            args.output,
            source_pdf=args.source_pdf,
            delete_spec=delete_spec,
            insert_ops=insert_ops,
            replace_spec=replace_spec,
        )
        return 0
    except ValueError as exc:
        parser.error(str(exc))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())