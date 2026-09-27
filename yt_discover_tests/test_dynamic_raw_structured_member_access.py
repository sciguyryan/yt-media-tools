"""Dynamic raw structured member access coverage."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import QuerySyntaxError, apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.query_types import StructuredShape
from yt_media_tools.schema import QuerySchema


def _resolve(source: str, records: list[dict[str, object]]):
    return resolve_query(parse_query(source), QuerySchema(records), DateContext())


def test_direct_raw_record_exposes_compatible_dynamic_members() -> None:
    records = [
        {"_raw": {"record": {"provider_id": "a", "height": 720}}},
        {"_raw": {"record": {"provider_id": "b", "height": 1080}}},
    ]
    schema = QuerySchema(records)
    info = schema.resolve("raw.record")

    assert info is not None
    assert info.query_type.structured_shape is StructuredShape.DYNAMIC
    assert info.query_type.declared_member_type("provider_id") is not None
    assert info.query_type.declared_member_type("height") is not None

    query = _resolve("SELECT (raw.record).provider_id AS provider_id", records)
    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "a"


def test_indexed_raw_record_collection_supports_member_access() -> None:
    records = [
        {
            "_raw": {
                "formats": [
                    {"format_id": "18", "height": 360},
                    {"format_id": "22", "height": 720},
                ]
            }
        }
    ]
    query = _resolve("SELECT raw.formats[1].format_id AS format_id", records)

    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == "22"


def test_nested_dynamic_raw_member_chain_is_typed_and_evaluated() -> None:
    records = [
        {"_raw": {"record": {"dimensions": {"width": 1920, "height": 1080}}}},
        {"_raw": {"record": {"dimensions": {"width": 1280}}}},
    ]
    query = _resolve("SELECT (raw.record).dimensions.height AS height", records)

    assert evaluate_scalar_expression(query.select[0].expression, records[0]) == 1080
    assert evaluate_scalar_expression(query.select[0].expression, records[1]) is None


def test_dynamic_member_missing_from_some_records_is_nullable() -> None:
    records = [
        {"_raw": {"record": {"provider_id": "a", "label": "first"}}},
        {"_raw": {"record": {"provider_id": "b"}}},
    ]
    schema = QuerySchema(records)
    info = schema.resolve("raw.record")

    assert info is not None
    label_type = info.query_type.declared_member_type("label")
    assert label_type is not None
    assert label_type.nullable is True


def test_incompatible_dynamic_member_is_not_exposed() -> None:
    records = [
        {"_raw": {"record": {"provider_id": "a", "value": "text"}}},
        {"_raw": {"record": {"provider_id": "b", "value": {"nested": 1}}}},
    ]

    with pytest.raises(QuerySyntaxError, match="Structured value has no member 'value'\\."):
        _resolve("SELECT (raw.record).value AS value", records)


def test_incompatible_raw_record_shape_remains_opaque() -> None:
    records = [
        {"_raw": {"records": [{"provider_id": "a"}, {"provider_id": "b"}]}},
        {"_raw": {"records": [{1: "not-a-string-key"}]}},
    ]
    schema = QuerySchema(records)
    info = schema.resolve_index_operand("raw.records")

    assert info is not None
    assert info.query_type.element_type is not None
    assert info.query_type.element_type.structured_shape is StructuredShape.OPAQUE

    with pytest.raises(
        QuerySyntaxError,
        match="Structured member access requires a declared member schema; got opaque structured value\\.",
    ):
        _resolve("SELECT raw.records[0].provider_id AS provider_id", records)


def test_raw_structured_value_cannot_be_selected_whole() -> None:
    records = [{"_raw": {"record": {"provider_id": "a"}}}]

    with pytest.raises(QuerySyntaxError, match="Cannot SELECT structured"):
        _resolve("SELECT raw.record", records)


def test_dynamic_raw_member_can_participate_in_predicate() -> None:
    records = [
        {"id": "a", "_raw": {"record": {"height": 720}}},
        {"id": "b", "_raw": {"record": {"height": 1080}}},
        {"id": "c", "_raw": {"record": {}}},
    ]
    query = _resolve("SELECT id WHERE (raw.record).height = 720 ORDER BY id", records)

    assert [row["id"] for row in apply_query(records, query)] == ["a"]
