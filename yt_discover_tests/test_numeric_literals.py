"""Numeric literal syntax and mixed-base scalar-expression coverage."""

from __future__ import annotations

from datetime import datetime

import pytest

from yt_discover_tests.conformance.generate_dataset import GENERATED_AT, PROFILE_SIZES, build_records
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import QuerySyntaxError, apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def _records() -> list[dict[str, object]]:
    records = []
    for source_index, raw in enumerate(build_records(PROFILE_SIZES["small"]), start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        records.append(record)
    return records


def _resolve(query: str):
    records = _records()
    resolved = resolve_query(
        parse_query(query),
        QuerySchema(records),
        DateContext(date_order="dmy", now=datetime.fromisoformat(GENERATED_AT)),
    )
    return records, resolved


def _project(query: str) -> object:
    records, resolved = _resolve(query)
    row = apply_query(records, resolved)[0]
    return evaluate_scalar_expression(resolved.select[0].expression, row)


@pytest.mark.parametrize(
    ("literal", "expected"),
    (
        ("1_000_000", 1_000_000),
        ("0007", 7),
        ("0xFF", 255),
        ("0Xff_FF", 65_535),
        ("0o755", 493),
        ("0O7_5_5", 493),
        ("0b1010_0101", 165),
        ("0B1_0_1", 5),
    ),
)
def test_integer_literal_bases_and_separators(literal: str, expected: int) -> None:
    assert _project(f"SELECT {literal} AS value FROM @yt_sql_fixture LIMIT 1") == expected


def test_mixed_base_arithmetic() -> None:
    assert _project("SELECT 0x10 + 0o10 + 0b10 + 10 AS value FROM @yt_sql_fixture LIMIT 1") == 36
    assert _project("SELECT (0x20 - 0b10) * 0o2 AS value FROM @yt_sql_fixture LIMIT 1") == 60


def test_non_decimal_literals_work_in_char_and_predicates() -> None:
    assert _project("SELECT CHAR(0x41, 0o102, 0b1000011) AS value FROM @yt_sql_fixture LIMIT 1") == "ABC"
    records, resolved = _resolve(
        "SELECT id FROM @yt_sql_fixture WHERE view_count >= 0xF4240 ORDER BY source_index ASC LIMIT 8"
    )
    assert apply_query(records, resolved)


def test_mixed_base_constants_fold_to_the_same_value() -> None:
    records, resolved = _resolve(
        "SELECT 0x10 + 0o10 + 0b10 + 10 AS value FROM @yt_sql_fixture ORDER BY 0x20 - 0b1 LIMIT 1"
    )
    result = optimise_query(resolved)
    assert apply_query(records, result.query) == apply_query(records, resolved)
    assert result.query.select[0].field == "36"
    assert result.query.order_by[0].field == "31"


@pytest.mark.parametrize(
    "literal",
    (
        "1__000",
        "1_",
        "0x",
        "0x_FF",
        "0xFF_",
        "0xFF__AA",
        "0xGG",
        "0o8",
        "0o_755",
        "0b102",
        "0b_101",
        "0b101_",
    ),
)
def test_malformed_numeric_literals_are_rejected(literal: str) -> None:
    with pytest.raises(QuerySyntaxError):
        parse_query(f"SELECT {literal} AS value FROM @yt_sql_fixture")


def test_comma_grouping_is_not_a_numeric_literal() -> None:
    with pytest.raises(QuerySyntaxError):
        _resolve("SELECT id FROM @yt_sql_fixture WHERE view_count >= 1,000,000")


def test_limit_and_offset_keep_decimal_underscore_syntax() -> None:
    query = parse_query("SELECT id FROM @yt_sql_fixture LIMIT 1_0 OFFSET 0_2")
    assert query.limit == 10
    assert query.offset == 2
