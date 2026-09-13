"""Dynamic raw collection indexing coverage."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import QuerySyntaxError, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.query_properties import IndexedFieldRequirement, analyse_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.sources import resolve_source


def _resolve(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext())


def test_raw_scalar_array_is_indexable_in_provider_sequence_order() -> None:
    records = [{"_raw": {"keywords": ["beta", "alpha"]}}]
    query = _resolve("SELECT raw.keywords[0] AS keyword", records)

    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "beta"


def test_raw_structured_array_index_does_not_make_structured_values_selectable() -> None:
    records = [{"_raw": {"formats": [{"format_id": "18"}, {"format_id": "22"}]}}]

    with pytest.raises(QuerySyntaxError, match="Cannot SELECT structured"):
        _resolve("SELECT raw.formats[1] AS format_record", records)


def test_nested_raw_arrays_can_be_indexed_repeatedly() -> None:
    records = [{"_raw": {"matrix": [["a", "b"], ["c", "d"]]}}]
    query = _resolve("SELECT raw.matrix[1][0] AS value", records)

    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "c"


def test_raw_null_and_out_of_range_access_use_null_semantics() -> None:
    records = [{"_raw": {"keywords": None}}, {"_raw": {"keywords": ["alpha"]}}]
    query = _resolve("SELECT raw.keywords[4] AS keyword", records)

    assert evaluate_scalar_expression(query.select[0].expression, records[0]) is None
    assert evaluate_scalar_expression(query.select[0].expression, records[1]) is None


@pytest.mark.parametrize(
    ("records", "message"),
    (
        ([{"_raw": {"keywords": "alpha"}}], "Collection indexing requires a collection value; got string."),
        (
            [{"_raw": {"keywords": {"alpha", "beta"}}}],
            "Collection indexing requires a stable logical collection ordering.",
        ),
        (
            [{"_raw": {"keywords": ["alpha"]}}, {"_raw": {"keywords": "beta"}}],
            "Collection indexing requires a collection value; got structured.",
        ),
    ),
)
def test_invalid_raw_indexing_is_rejected_deterministically(records: list[dict[str, object]], message: str) -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        _resolve("SELECT raw.keywords[0]", records)

    assert exc_info.value.message == message


def test_raw_direct_index_is_preserved_as_backend_specific_requirement() -> None:
    records = [{"_raw": {"keywords": ["alpha", "beta"]}}]
    query = _resolve("SELECT raw.keywords[1] AS keyword", records)

    properties = analyse_query(query, source=resolve_source("@whatdamath"))

    assert IndexedFieldRequirement("raw.keywords", 1) in properties.indexed_requirements
    assert "raw.keywords" in properties.required_fields
