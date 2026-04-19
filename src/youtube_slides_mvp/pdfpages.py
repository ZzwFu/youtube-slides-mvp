from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import logging
import re
from collections.abc import Sequence
from pathlib import Path

import fitz

__all__ = [
    "EditPlan",
    "build_edit_plan",
    "expand_page_spec",
    "edit_pdf_pages",
    "delete_pdf_pages",
    "insert_pdf_pages",
    "replace_pdf_pages",
]

_WHITESPACE_RE = re.compile(r"\s+")
_TIME_UNIT_RE = re.compile(r"^(?:(?P<h>\d+)h)?(?:(?P<m>\d+)m)?(?:(?P<s>\d+(?:\.\d+)?)s?)?$")
LOGGER = logging.getLogger(__name__)


@dataclass
class EditPlan:
    """Normalized editing plan in original input-page coordinates."""

    input_page_count: int
    delete_pages: set[int]
    replacement_map: dict[int, int]
    insert_groups: dict[int, list[list[int]]]

    @property
    def inserted_page_count(self) -> int:
        return sum(len(group) for groups in self.insert_groups.values() for group in groups)

    @property
    def output_page_count(self) -> int:
        return self.input_page_count - len(self.delete_pages) + self.inserted_page_count


def _normalize_page_spec(spec: str) -> str:
    cleaned = _WHITESPACE_RE.sub("", spec)
    if not cleaned:
        raise ValueError("page specification is empty")
    return cleaned


def _normalize_source_spec(spec: str) -> str:
    cleaned = _WHITESPACE_RE.sub("", spec)
    if not cleaned:
        raise ValueError("source specification is empty")
    return cleaned


def _validate_page_number(page_number: int, total_pages: int) -> int:
    if page_number < 1:
        raise ValueError("page numbers are 1-based")
    if page_number > total_pages:
        raise ValueError(f"page {page_number} exceeds document length {total_pages}")
    return page_number


def _parse_endpoint(token: str, total_pages: int) -> int:
    if not token:
        raise ValueError("page specification has an empty endpoint")

    lowered = token.lower()
    if lowered in {"last", "-1"}:
        return total_pages
    if token.isdigit():
        return _validate_page_number(int(token), total_pages)
    raise ValueError(f"invalid page token: {token!r}")


def _parse_time_seconds(token: str) -> float:
    if not token.startswith("@"):
        raise ValueError(f"invalid time token: {token!r}")

    body = token[1:]
    if not body:
        raise ValueError("time specification has an empty endpoint")

    if ":" in body:
        parts = body.split(":")
        if len(parts) == 2:
            minutes_raw, seconds_raw = parts
            hours = 0
        elif len(parts) == 3:
            hours_raw, minutes_raw, seconds_raw = parts
            try:
                hours = int(hours_raw)
            except ValueError as exc:  # noqa: BLE001
                raise ValueError(f"invalid time token: {token!r}") from exc
        else:
            raise ValueError(f"invalid time token: {token!r}")

        try:
            minutes = int(minutes_raw)
            seconds = float(seconds_raw)
        except ValueError as exc:  # noqa: BLE001
            raise ValueError(f"invalid time token: {token!r}") from exc
        if hours < 0 or minutes < 0 or seconds < 0:
            raise ValueError(f"invalid time token: {token!r}")
        return hours * 3600.0 + minutes * 60.0 + seconds

    unit_match = _TIME_UNIT_RE.fullmatch(body)
    if unit_match and any(unit_match.group(name) is not None for name in ("h", "m", "s")):
        hours = int(unit_match.group("h") or 0)
        minutes = int(unit_match.group("m") or 0)
        seconds = float(unit_match.group("s") or 0)
        return hours * 3600.0 + minutes * 60.0 + seconds

    try:
        seconds = float(body[:-1] if body.endswith("s") else body)
    except ValueError as exc:  # noqa: BLE001
        raise ValueError(f"invalid time token: {token!r}") from exc

    if seconds < 0:
        raise ValueError(f"invalid time token: {token!r}")
    return seconds


def _build_time_index(source_rows: Sequence[dict[str, int | float | str]]) -> tuple[list[int], list[float]]:
    if not source_rows:
        raise ValueError("time-based source specs require source index data")

    page_numbers: list[int] = []
    timestamps: list[float] = []
    previous_timestamp: float | None = None

    for index, row in enumerate(source_rows, start=1):
        if not isinstance(row, dict):
            raise ValueError("source index rows must be mappings")

        timestamp_raw = row.get("timestamp_sec")
        if timestamp_raw is None:
            timestamp_ms_raw = row.get("timestamp_ms")
            if timestamp_ms_raw is None:
                raise ValueError("source index rows must include timestamp_sec or timestamp_ms")
            timestamp = float(timestamp_ms_raw) / 1000.0
        else:
            timestamp = float(timestamp_raw)

        if timestamp < 0:
            raise ValueError("source timestamps must be non-negative")
        if previous_timestamp is not None and timestamp < previous_timestamp:
            raise ValueError("source index must be sorted by timestamp")
        previous_timestamp = timestamp

        page_number_raw = row.get("page")
        if page_number_raw is None:
            page_number_raw = row.get("frame_index", index)
        page_number = int(page_number_raw)
        if page_number < 1:
            raise ValueError("source page numbers are 1-based")

        page_numbers.append(page_number)
        timestamps.append(timestamp)

    return page_numbers, timestamps


def _time_index_for_timestamp(timestamp: float, timestamps: Sequence[float]) -> int:
    index = bisect_right(timestamps, timestamp) - 1
    if index < 0:
        return 0
    if index >= len(timestamps):
        return len(timestamps) - 1
    return index


def _split_replace_spec(replace_spec: str) -> tuple[str, str, str]:
    for separator in ("=", ">", ":"):
        if separator not in replace_spec:
            continue

        target_spec, source_spec = replace_spec.split(separator, 1)
        if not target_spec or not source_spec:
            break
        return separator, target_spec, source_spec

    raise ValueError("--replace must use TARGET=SOURCE page lists")


def expand_page_spec(spec: str, total_pages: int) -> list[int]:
    """Expand a flexible page specification into 1-based page numbers.

    Supported forms:
    - 3
    - 3-7
    - 3,5,7
    - 5-
    - -5
    - 1,3-5,8-
    - last or -1
    """

    if total_pages < 1:
        raise ValueError("document has no pages")

    cleaned = _normalize_page_spec(spec)
    pages: list[int] = []

    for raw_token in cleaned.split(","):
        if not raw_token:
            raise ValueError(f"invalid page specification: {spec!r}")

        token = raw_token.lower()
        if token in {"last", "-1"}:
            pages.append(total_pages)
            continue

        if raw_token.startswith("-") and raw_token[1:].isdigit() and raw_token != "-1":
            end = _validate_page_number(int(raw_token[1:]), total_pages)
            pages.extend(range(1, end + 1))
            continue

        if raw_token.endswith("-") and raw_token != "-":
            start = _parse_endpoint(raw_token[:-1], total_pages)
            pages.extend(range(start, total_pages + 1))
            continue

        if raw_token.count("-") == 1:
            left, right = raw_token.split("-", 1)
            start = _parse_endpoint(left, total_pages)
            end = _parse_endpoint(right, total_pages)
            if start > end:
                raise ValueError(f"invalid page range {raw_token!r}: start exceeds end")
            pages.extend(range(start, end + 1))
            continue

        pages.append(_parse_endpoint(raw_token, total_pages))

    return pages


def _expand_time_token(
    raw_token: str,
    page_numbers: Sequence[int],
    timestamps: Sequence[float],
) -> list[int]:
    if raw_token.startswith("-@"):
        end_time = _parse_time_seconds(raw_token[1:])
        end_index = _time_index_for_timestamp(end_time, timestamps)
        return list(page_numbers[: end_index + 1])

    if raw_token.endswith("-") and raw_token != "-":
        start_token = raw_token[:-1]
        if not start_token.startswith("@"):
            raise ValueError("time-based source specs must use @ timestamps")
        start_time = _parse_time_seconds(start_token)
        start_index = _time_index_for_timestamp(start_time, timestamps)
        return list(page_numbers[start_index:])

    if raw_token.count("-") == 1:
        left, right = raw_token.split("-", 1)
        if not left.startswith("@") or not right.startswith("@"):
            raise ValueError("time-based source specs must use @ timestamps")
        start_time = _parse_time_seconds(left)
        end_time = _parse_time_seconds(right)
        if start_time > end_time:
            raise ValueError(f"invalid time range {raw_token!r}: start exceeds end")
        start_index = _time_index_for_timestamp(start_time, timestamps)
        end_index = _time_index_for_timestamp(end_time, timestamps)
        return list(page_numbers[start_index : end_index + 1])

    if not raw_token.startswith("@"):
        raise ValueError("time-based source specs must use @ timestamps")

    point_time = _parse_time_seconds(raw_token)
    point_index = _time_index_for_timestamp(point_time, timestamps)
    return [page_numbers[point_index]]


def _expand_source_spec(
    spec: str,
    source_page_count: int,
    source_rows: Sequence[dict[str, int | float | str]] | None = None,
) -> list[int]:
    cleaned = _normalize_source_spec(spec)
    pages: list[int] = []
    time_index: tuple[list[int], list[float]] | None = None

    for raw_token in cleaned.split(","):
        if not raw_token:
            raise ValueError(f"invalid source specification: {spec!r}")

        if "@" in raw_token:
            if source_rows is None:
                raise ValueError("time-based source specs require source index data")
            if time_index is None:
                time_index = _build_time_index(source_rows)
            page_numbers, timestamps = time_index
            pages.extend(_expand_time_token(raw_token, page_numbers, timestamps))
            continue

        pages.extend(expand_page_spec(raw_token, source_page_count))

    return pages


def _open_pdf(path: Path) -> fitz.Document:
    if not path.exists():
        raise ValueError(f"PDF not found: {path}")

    try:
        return fitz.open(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"unable to open PDF {path}: {exc}") from exc


def _append_pages(out_doc: fitz.Document, src_doc: fitz.Document, page_numbers: list[int]) -> None:
    for page_number in page_numbers:
        out_doc.insert_pdf(
            src_doc,
            from_page=page_number - 1,
            to_page=page_number - 1,
            links=True,
            annots=True,
        )


def _save_document(doc: fitz.Document, out_pdf: Path) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    temp_pdf = out_pdf.with_name(f"{out_pdf.name}.tmp")
    temp_pdf.unlink(missing_ok=True)
    try:
        doc.save(str(temp_pdf))
        temp_pdf.replace(out_pdf)
    finally:
        temp_pdf.unlink(missing_ok=True)


def _parse_replace_spec(
    replace_spec: str,
    input_page_count: int,
    source_page_count: int,
    source_rows: Sequence[dict[str, int | float | str]] | None = None,
) -> dict[int, int]:
    _, target_spec, source_spec = _split_replace_spec(replace_spec)

    target_pages = expand_page_spec(target_spec, input_page_count)
    if len(set(target_pages)) != len(target_pages):
        raise ValueError("--replace target pages must not repeat")

    source_pages = _expand_source_spec(source_spec, source_page_count, source_rows)
    if len(target_pages) != len(source_pages):
        raise ValueError("--replace target and source page lists must have the same length")

    return dict(zip(target_pages, source_pages))


def build_edit_plan(
    *,
    input_page_count: int,
    source_page_count: int | None,
    source_rows: Sequence[dict[str, int | float | str]] | None,
    delete_spec: str | None,
    insert_ops: list[tuple[str, int]] | None,
    replace_spec: str | None,
) -> EditPlan:
    """Build and validate an immutable edit plan before any PDF output is written."""
    delete_pages: set[int] = set()
    if delete_spec is not None:
        delete_pages = set(expand_page_spec(delete_spec, input_page_count))

    replacement_map: dict[int, int] = {}
    if replace_spec is not None:
        if source_page_count is None:
            raise ValueError("--from is required with --replace")
        replacement_map = _parse_replace_spec(
            replace_spec,
            input_page_count,
            source_page_count,
            source_rows,
        )

    insert_groups: dict[int, list[list[int]]] = {}
    if insert_ops:
        if source_page_count is None:
            raise ValueError("--from is required with --insert")

        for insert_spec, after in insert_ops:
            if after < 0:
                raise ValueError("--after must be >= 0")
            if after > input_page_count:
                raise ValueError(f"--after {after} exceeds input document length {input_page_count}")
            insert_pages = _expand_source_spec(insert_spec, source_page_count, source_rows)
            insert_groups.setdefault(after, []).append(insert_pages)

    overlap = sorted(delete_pages & replacement_map.keys())
    if overlap:
        overlap_text = ", ".join(str(page) for page in overlap)
        raise ValueError(f"--delete and --replace target the same page(s): {overlap_text}")

    return EditPlan(
        input_page_count=input_page_count,
        delete_pages=delete_pages,
        replacement_map=replacement_map,
        insert_groups=insert_groups,
    )


def _copy_document_metadata(input_doc: fitz.Document, out_doc: fitz.Document) -> None:
    try:
        metadata = input_doc.metadata or {}
        cleaned = {key: value for key, value in metadata.items() if isinstance(value, str)}
        if cleaned:
            out_doc.set_metadata(cleaned)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Unable to preserve PDF metadata: %s", exc)


def _build_original_to_output_page_map(plan: EditPlan) -> dict[int, int]:
    mapping: dict[int, int] = {}
    output_page = 1

    for insert_pages in plan.insert_groups.get(0, []):
        output_page += len(insert_pages)

    for page_number in range(1, plan.input_page_count + 1):
        if page_number not in plan.delete_pages:
            mapping[page_number] = output_page
            output_page += 1

        for insert_pages in plan.insert_groups.get(page_number, []):
            output_page += len(insert_pages)

    return mapping


def _normalize_toc_levels(entries: list[list[int | str]]) -> list[list[int | str]]:
    normalized: list[list[int | str]] = []
    previous_level = 1

    for index, entry in enumerate(entries):
        level = int(entry[0])
        title = str(entry[1])
        page = int(entry[2])

        level = max(1, level)
        if index == 0:
            level = 1
        elif level > previous_level + 1:
            level = previous_level + 1

        normalized.append([level, title, page])
        previous_level = level

    return normalized


def _copy_toc_with_page_remap(input_doc: fitz.Document, out_doc: fitz.Document, plan: EditPlan) -> None:
    try:
        toc = input_doc.get_toc(simple=True)
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Unable to read input TOC: %s", exc)
        return

    if not toc:
        return

    page_map = _build_original_to_output_page_map(plan)
    remapped: list[list[int | str]] = []
    for row in toc:
        if len(row) < 3:
            continue

        level, title, original_page = row[:3]
        mapped_page = page_map.get(int(original_page))
        if mapped_page is None:
            continue
        remapped.append([int(level), str(title), mapped_page])

    if not remapped:
        LOGGER.info("TOC entries were dropped because their target pages were deleted")
        return

    try:
        out_doc.set_toc(_normalize_toc_levels(remapped))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Unable to set remapped TOC in output PDF: %s", exc)


def _apply_edit_plan(
    out_doc: fitz.Document,
    input_doc: fitz.Document,
    source_doc: fitz.Document | None,
    plan: EditPlan,
) -> None:
    if 0 in plan.insert_groups:
        assert source_doc is not None
        for insert_pages in plan.insert_groups[0]:
            _append_pages(out_doc, source_doc, insert_pages)

    for page_number in range(1, plan.input_page_count + 1):
        if page_number not in plan.delete_pages:
            source_page = plan.replacement_map.get(page_number)
            if source_page is None:
                out_doc.insert_pdf(
                    input_doc,
                    from_page=page_number - 1,
                    to_page=page_number - 1,
                    links=True,
                    annots=True,
                )
            else:
                assert source_doc is not None
                out_doc.insert_pdf(
                    source_doc,
                    from_page=source_page - 1,
                    to_page=source_page - 1,
                    links=True,
                    annots=True,
                )

        if page_number in plan.insert_groups:
            assert source_doc is not None
            for insert_pages in plan.insert_groups[page_number]:
                _append_pages(out_doc, source_doc, insert_pages)


def edit_pdf_pages(
    input_pdf: Path,
    output_pdf: Path,
    *,
    source_pdf: Path | None = None,
    source_rows: Sequence[dict[str, int | float | str]] | None = None,
    delete_spec: str | None = None,
    insert_ops: list[tuple[str, int]] | None = None,
    replace_spec: str | None = None,
    dry_run: bool = False,
    preserve_metadata: bool = True,
    preserve_toc: bool = True,
) -> int:
    input_doc = _open_pdf(input_pdf)
    source_doc: fitz.Document | None = None
    try:
        input_page_count = input_doc.page_count

        source_page_count: int | None = None
        requires_source = bool(insert_ops) or replace_spec is not None
        if requires_source:
            if source_pdf is None:
                raise ValueError("--from is required with --insert or --replace")
            source_doc = _open_pdf(source_pdf)
            source_page_count = source_doc.page_count
            if source_rows is not None and source_page_count != len(source_rows):
                raise ValueError("source index length does not match source PDF page count")

        plan = build_edit_plan(
            input_page_count=input_page_count,
            source_page_count=source_page_count,
            source_rows=source_rows,
            delete_spec=delete_spec,
            insert_ops=insert_ops,
            replace_spec=replace_spec,
        )

        LOGGER.debug(
            "Built edit plan: input_pages=%s delete=%s replace=%s insert_groups=%s output_pages=%s",
            plan.input_page_count,
            len(plan.delete_pages),
            len(plan.replacement_map),
            len(plan.insert_groups),
            plan.output_page_count,
        )

        if dry_run:
            return plan.output_page_count

        out_doc = fitz.open()
        try:
            _apply_edit_plan(out_doc, input_doc, source_doc, plan)

            if preserve_metadata:
                _copy_document_metadata(input_doc, out_doc)
            if preserve_toc:
                _copy_toc_with_page_remap(input_doc, out_doc, plan)

            out_pages = out_doc.page_count
            _save_document(out_doc, output_pdf)
            return out_pages
        finally:
            out_doc.close()
    finally:
        if source_doc is not None:
            source_doc.close()
        input_doc.close()


def delete_pdf_pages(input_pdf: Path, delete_spec: str, output_pdf: Path) -> int:
    return edit_pdf_pages(input_pdf, output_pdf, delete_spec=delete_spec)


def insert_pdf_pages(
    input_pdf: Path,
    source_pdf: Path,
    insert_spec: str,
    after: int,
    output_pdf: Path,
    *,
    source_rows: Sequence[dict[str, int | float | str]] | None = None,
) -> int:
    return edit_pdf_pages(
        input_pdf,
        output_pdf,
        source_pdf=source_pdf,
        source_rows=source_rows,
        insert_ops=[(insert_spec, after)],
    )


def replace_pdf_pages(
    input_pdf: Path,
    source_pdf: Path,
    replace_spec: str,
    output_pdf: Path,
    *,
    source_rows: Sequence[dict[str, int | float | str]] | None = None,
) -> int:
    return edit_pdf_pages(
        input_pdf,
        output_pdf,
        source_pdf=source_pdf,
        source_rows=source_rows,
        replace_spec=replace_spec,
    )