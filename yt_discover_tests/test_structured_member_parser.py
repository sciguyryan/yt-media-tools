"""Parser and formatter coverage for postfix structured member syntax."""

from __future__ import annotations

import pytest

from yt_media_tools.query import ScalarFunction, ScalarIndex, ScalarMember
from yt_media_tools.query_formatter import format_query, format_scalar_expression
from yt_media_tools.query_model import Field, QuerySyntaxError
from yt_media_tools.query_parser import parse_query, tokenise


def _select_expression(source: str):
    return parse_query(source).select[0].expression


def test_tokeniser_recognises_postfix_member_delimiter() -> None:
    tokens = tokenise("SELECT formats[0].height FROM @fixture")
    assert [(token.kind, token.text) for token in tokens if token.kind == "DOT"] == [("DOT", ".")]


def test_member_access_builds_distinct_postfix_ast_node() -> None:
    expression = _select_expression("SELECT formats[0].height FROM @fixture")
    assert isinstance(expression, ScalarMember)
    assert expression.member == "height"
    assert isinstance(expression.value, ScalarIndex)
    assert format_scalar_expression(expression) == "formats[0].height"


def test_member_access_can_chain_after_indexing() -> None:
    expression = _select_expression("SELECT formats[0].video.height FROM @fixture")
    assert isinstance(expression, ScalarMember)
    assert expression.member == "height"
    assert isinstance(expression.value, ScalarMember)
    assert expression.value.member == "video"
    assert isinstance(expression.value.value, ScalarIndex)
    assert format_scalar_expression(expression) == "formats[0].video.height"


def test_member_access_and_indexing_can_interleave() -> None:
    expression = _select_expression("SELECT matrix[0].values[1].name FROM @fixture")
    assert isinstance(expression, ScalarMember)
    assert expression.member == "name"
    assert isinstance(expression.value, ScalarIndex)
    assert isinstance(expression.value.collection, ScalarMember)
    assert format_scalar_expression(expression) == "matrix[0].values[1].name"


def test_function_result_can_use_member_access() -> None:
    expression = _select_expression("SELECT COALESCE(record, fallback).height FROM @fixture")
    assert isinstance(expression, ScalarMember)
    assert isinstance(expression.value, ScalarFunction)
    assert format_scalar_expression(expression) == "COALESCE(record, fallback).height"


def test_parenthesised_expression_can_use_member_access() -> None:
    expression = _select_expression("SELECT (record).height FROM @fixture")
    assert isinstance(expression, ScalarMember)
    assert expression.value == Field("record", 8)
    assert format_scalar_expression(expression) == "(record).height"
    reparsed = _select_expression(f"SELECT {format_scalar_expression(expression)} FROM @fixture")
    assert isinstance(reparsed, ScalarMember)
    assert reparsed.member == "height"


def test_existing_bare_dotted_field_paths_remain_fields() -> None:
    expression = _select_expression("SELECT raw.extra.score FROM @fixture")
    assert expression == Field("raw.extra.score", 7)
    assert format_scalar_expression(expression) == "raw.extra.score"


@pytest.mark.parametrize(
    "source",
    (
        "SELECT formats[0]. FROM @fixture",
        "SELECT formats[0]..height FROM @fixture",
        "SELECT formats[0].123 FROM @fixture",
    ),
)
def test_malformed_member_access_diagnostic_is_deterministic(source: str) -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        parse_query(source)
    assert exc_info.value.message == "Expected a member name after '.'."


def test_structured_member_canonical_format_round_trip() -> None:
    source = "SELECT matrix[0].values[1].name AS item FROM @fixture ORDER BY matrix[1].values[0].name DESC"
    canonical = format_query(parse_query(source))
    assert canonical == source
    assert format_query(parse_query(canonical)) == canonical
