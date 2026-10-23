"""Integer-base and canonical-formatting coverage for LIMIT and OFFSET."""

from __future__ import annotations

import pytest

from yt_media_tools.query import merge_queries
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_parser import parse_query


@pytest.mark.parametrize(
    ("source", "limit", "offset", "canonical_suffix"),
    (
        ("SELECT id LIMIT 255", 255, 0, "LIMIT 255"),
        ("SELECT id LIMIT 0XFF", 255, 0, "LIMIT 0xff"),
        ("SELECT id LIMIT 0o7_55", 493, 0, "LIMIT 0o755"),
        ("SELECT id LIMIT 0B1010_0101", 165, 0, "LIMIT 0b10100101"),
        ("SELECT id LIMIT 0xff OFFSET 0X10", 255, 16, "LIMIT 0xff OFFSET 0x10"),
        ("SELECT id OFFSET 0x0", None, 0, "OFFSET 0x0"),
    ),
)
def test_row_slicing_accepts_integer_bases_and_preserves_canonical_base(
    source: str, limit: int | None, offset: int, canonical_suffix: str
) -> None:
    reference = parse_query(source)

    assert reference.limit == limit
    assert reference.offset == offset
    assert format_query(reference).endswith(canonical_suffix)
    assert format_query(parse_query(format_query(reference))) == format_query(reference)


@pytest.mark.parametrize(
    "source",
    (
        "SELECT id LIMIT 0x0",
        "SELECT id LIMIT 0b0",
        "SELECT id LIMIT 0o0",
        "SELECT id LIMIT 0xGG",
        "SELECT id LIMIT 0b102",
        "SELECT id LIMIT 0o89",
        "SELECT id OFFSET 0xGG",
        "SELECT id OFFSET -0x1",
        "SELECT id LIMIT 1.5",
        "SELECT id LIMIT 1k",
        "SELECT id LIMIT 0x",
    ),
)
def test_row_slicing_rejects_zero_limit_and_non_integer_forms(source: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(source)


def test_explicit_zero_offset_overrides_a_merged_base_offset() -> None:
    merged = merge_queries(parse_query("SELECT id OFFSET 0x10"), parse_query("SELECT title OFFSET 0b0"))

    assert merged.offset == 0
    assert format_query(merged).endswith("OFFSET 0b0")
