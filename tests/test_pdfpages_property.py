from __future__ import annotations

import pytest

pytest.importorskip("hypothesis")

from hypothesis import given
from hypothesis import strategies as st

from src.youtube_slides_mvp.pdfpages import _split_replace_spec, expand_page_spec


@st.composite
def _page_spec_case(draw: st.DrawFn) -> tuple[int, str, list[int]]:
    total_pages = draw(st.integers(min_value=1, max_value=40))
    token_count = draw(st.integers(min_value=1, max_value=8))

    tokens: list[str] = []
    expected: list[int] = []

    for _ in range(token_count):
        token_kind = draw(st.sampled_from(["single", "closed", "prefix", "suffix", "last"]))

        if token_kind == "single":
            page = draw(st.integers(min_value=1, max_value=total_pages))
            base_token = str(page)
            expanded = [page]
        elif token_kind == "closed":
            start = draw(st.integers(min_value=1, max_value=total_pages))
            end = draw(st.integers(min_value=start, max_value=total_pages))
            base_token = f"{start}-{end}"
            expanded = list(range(start, end + 1))
        elif token_kind == "prefix":
            if total_pages == 1:
                base_token = "1"
                expanded = [1]
            else:
                end = draw(st.integers(min_value=2, max_value=total_pages))
                base_token = f"-{end}"
                expanded = list(range(1, end + 1))
        elif token_kind == "suffix":
            start = draw(st.integers(min_value=1, max_value=total_pages))
            base_token = f"{start}-"
            expanded = list(range(start, total_pages + 1))
        else:
            base_token = draw(st.sampled_from(["last", "-1"]))
            expanded = [total_pages]

        token = draw(st.sampled_from([base_token, f" {base_token}", f"{base_token} ", f" {base_token} "]))
        tokens.append(token)
        expected.extend(expanded)

    spec = ",".join(tokens)
    return total_pages, spec, expected


@st.composite
def _flat_page_list_spec(draw: st.DrawFn) -> str:
    token_count = draw(st.integers(min_value=1, max_value=4))
    tokens = [str(draw(st.integers(min_value=1, max_value=40))) for _ in range(token_count)]
    return ",".join(tokens)


@given(case=_page_spec_case())
def test_expand_page_spec_property_matches_constructed_expectation(case: tuple[int, str, list[int]]) -> None:
    total_pages, spec, expected = case
    assert expand_page_spec(spec, total_pages) == expected


@given(
    separator=st.sampled_from(["=", ">", ":"]),
    left=_flat_page_list_spec(),
    right=_flat_page_list_spec(),
)
def test_split_replace_spec_accepts_supported_separators(
    separator: str,
    left: str,
    right: str,
) -> None:
    parsed_separator, parsed_left, parsed_right = _split_replace_spec(f"{left}{separator}{right}")
    assert parsed_separator == separator
    assert parsed_left == left
    assert parsed_right == right
