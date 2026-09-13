"""Semantic resolution and evaluation coverage for collection indexing."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import (
    QuerySyntaxError,
    ScalarIndex,
    evaluate_scalar_expression,
    parse_query,
    resolve_query,
)
from yt_media_tools.schema import QuerySchema


def _resolve(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext())


def test_indexing_resolves_collection_element_type_and_runtime_value() -> None:
    records = [{"id": "a", "tags": ["alpha", "beta"]}]
    query = _resolve("SELECT tags[1] AS tag", records)
    expression = query.select[0].expression
    assert isinstance(expression, ScalarIndex)
    assert expression.kind == "string"
    assert expression.resolved_type is not None
    assert expression.resolved_type.nullable is True
    assert evaluate_scalar_expression(expression, records[0]) == "beta"


def test_collection_index_is_zero_based_and_out_of_range_is_null() -> None:
    records = [{"id": "a", "tags": ["alpha"]}]
    query = _resolve("SELECT tags[0] AS first, tags[5] AS missing", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "alpha"
    assert evaluate_scalar_expression(query.select[1].expression, records[0]) is None


def test_null_collection_and_null_index_propagate_null() -> None:
    records = [{"id": "a", "tags": None}, {"id": "b", "tags": ["beta"]}]
    query = _resolve("SELECT tags[0] AS tag, tags[NULL] AS null_index ORDER BY id", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) is None
    assert evaluate_scalar_expression(query.select[0].expression, records[1]) == "beta"
    assert evaluate_scalar_expression(query.select[1].expression, records[0]) is None
    assert evaluate_scalar_expression(query.select[1].expression, records[1]) is None


def test_chained_indexing_resolves_nested_collection_elements() -> None:
    records = [{"matrix": [["a", "b"], ["c", "d"]]}]
    query = _resolve("SELECT matrix[1][0] AS item", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "c"


def test_constant_integer_index_expression_is_accepted() -> None:
    records = [{"tags": ["zero", "one", "two"]}]
    query = _resolve("SELECT tags[1 + 1] AS tag", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "two"


def test_integer_typed_runtime_index_is_accepted() -> None:
    records = [{"tags": ["zero", "one"], "playlist_index": 1}]
    query = _resolve("SELECT tags[playlist_index] AS tag", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "one"


def test_function_and_parenthesised_collection_expressions_can_be_indexed() -> None:
    records = [{"tags": ["alpha", "beta"]}]
    function_query = _resolve("SELECT COALESCE(tags, NULL)[0] AS tag", records)
    parenthesised_query = _resolve("SELECT (tags)[1] AS tag", records)
    assert evaluate_scalar_expression(function_query.select[0].expression, records[0]) == "alpha"
    assert evaluate_scalar_expression(parenthesised_query.select[0].expression, records[0]) == "beta"


@pytest.mark.parametrize(
    ("source", "message"),
    (
        ("SELECT id[0]", "Collection indexing requires a collection value; got string."),
        ("SELECT tags['0']", "Collection index must be an integer value."),
        ("SELECT tags[1.5]", "Collection index must be an integer value."),
        ("SELECT tags[-1]", "Collection index must not be negative."),
    ),
)
def test_incompatible_collection_index_types_are_rejected_deterministically(source: str, message: str) -> None:
    records = [{"id": "a", "tags": ["alpha"]}]
    with pytest.raises(QuerySyntaxError) as exc_info:
        _resolve(source, records)
    assert exc_info.value.message == message


def test_unordered_collection_rejects_positional_indexing() -> None:
    records = [{"labels": {"alpha", "beta"}}]
    with pytest.raises(QuerySyntaxError) as exc_info:
        _resolve("SELECT labels[0]", records)
    assert exc_info.value.message == "Collection indexing requires a stable logical collection ordering."


def test_raw_collection_path_can_be_indexed_when_runtime_value_is_ordered() -> None:
    records = [{"_raw": {"keywords": ["alpha", "beta"]}}]
    query = _resolve("SELECT raw.keywords[1] AS keyword", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "beta"
