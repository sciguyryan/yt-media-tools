"""Parser and formatter coverage for postfix collection indexing."""

from __future__ import annotations

import pytest

from yt_media_tools.query import ScalarBinary, ScalarFunction, ScalarIndex
from yt_media_tools.query_formatter import format_query, format_scalar_expression
from yt_media_tools.query_model import Field, Literal, QuerySyntaxError
from yt_media_tools.query_parser import parse_query, tokenise


def _select_expression(source: str):
    return parse_query(source).select[0].expression


def test_tokeniser_recognises_collection_index_delimiters() -> None:
    tokens = tokenise("SELECT tags[0] FROM @fixture")
    assert [(token.kind, token.text) for token in tokens if token.kind in {"LBRACKET", "RBRACKET"}] == [
        ("LBRACKET", "["),
        ("RBRACKET", "]"),
    ]


def test_indexing_builds_distinct_postfix_ast_node() -> None:
    expression = _select_expression("SELECT tags[0] FROM @fixture")
    assert expression == ScalarIndex(Field("tags", 7), Literal(0, "0", 12), 11)


def test_indexing_binds_more_tightly_than_arithmetic() -> None:
    expression = _select_expression("SELECT tags[0] + 1 FROM @fixture")
    assert isinstance(expression, ScalarBinary)
    assert isinstance(expression.left, ScalarIndex)
    assert format_scalar_expression(expression) == "(tags[0] + 1)"


def test_index_expression_accepts_general_scalar_expression() -> None:
    expression = _select_expression("SELECT tags[1 + 2] FROM @fixture")
    assert isinstance(expression, ScalarIndex)
    assert isinstance(expression.index, ScalarBinary)
    assert format_scalar_expression(expression) == "tags[(1 + 2)]"


def test_postfix_indexing_can_chain() -> None:
    expression = _select_expression("SELECT matrix[0][1] FROM @fixture")
    assert isinstance(expression, ScalarIndex)
    assert isinstance(expression.collection, ScalarIndex)
    assert format_scalar_expression(expression) == "matrix[0][1]"


def test_function_result_can_be_indexed() -> None:
    expression = _select_expression("SELECT COALESCE(tags, NULL)[0] FROM @fixture")
    assert isinstance(expression, ScalarIndex)
    assert isinstance(expression.collection, ScalarFunction)
    assert format_scalar_expression(expression) == "COALESCE(tags, NULL)[0]"


def test_parenthesised_expression_can_be_indexed() -> None:
    expression = _select_expression("SELECT (tags)[0] FROM @fixture")
    assert isinstance(expression, ScalarIndex)
    assert format_scalar_expression(expression) == "tags[0]"


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("SELECT tags[] FROM @fixture", "Collection indexing requires an index expression."),
        ("SELECT tags[0 FROM @fixture", "Expected ']' to close the collection index."),
    ),
)
def test_malformed_collection_index_diagnostics_are_deterministic(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        parse_query(source)
    assert exc_info.value.message == message


def test_collection_index_canonical_format_round_trip() -> None:
    source = "SELECT matrix[0][1] AS item FROM @fixture ORDER BY matrix[1][0] DESC"
    canonical = format_query(parse_query(source))
    assert canonical == source
    assert format_query(parse_query(canonical)) == canonical
