"""Runtime evaluation coverage for resolved structured member access."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.query import apply_query, evaluate_scalar_expression, parse_query, resolve_query
from yt_media_tools.query_types import CollectionOrdering, QueryType, StructuredMember, StructuredShape
from yt_media_tools.schema import FieldInfo, QuerySchema


def _record_type(*, nullable: bool = True) -> QueryType:
    dimensions = QueryType.structured(
        (
            StructuredMember("width", QueryType.scalar("count", nullable=False)),
            StructuredMember("height", QueryType.scalar("count", nullable=True)),
        ),
        nullable=False,
    )
    return QueryType.structured(
        (
            StructuredMember("height", QueryType.scalar("count", nullable=False)),
            StructuredMember("label", QueryType.scalar("string", nullable=True)),
            StructuredMember("dimensions", dimensions),
        ),
        nullable=nullable,
    )


def _schema() -> QuerySchema:
    record_type = _record_type()
    dynamic_type = QueryType.structured(
        (StructuredMember("provider_id", QueryType.scalar("string", nullable=False)),),
        nullable=True,
        shape=StructuredShape.DYNAMIC,
    )
    return QuerySchema.from_field_infos(
        (
            FieldInfo("id", "string", False),
            FieldInfo("record", "structured", True, resolved_type=record_type),
            FieldInfo(
                "records",
                "collection",
                False,
                resolved_type=QueryType.collection(
                    record_type.with_nullable(False),
                    nullable=False,
                    ordering=CollectionOrdering.STABLE,
                ),
            ),
            FieldInfo("dynamic_record", "structured", True, resolved_type=dynamic_type),
        )
    )


def _resolve(source: str):
    return resolve_query(parse_query(source), _schema(), DateContext())


def test_member_evaluation_returns_declared_runtime_value() -> None:
    row = {"record": {"height": 720, "label": "HD"}}
    query = _resolve("SELECT (record).height AS height")
    assert evaluate_scalar_expression(query.select[0].expression, row) == 720


def test_null_structured_base_propagates_sql_null() -> None:
    query = _resolve("SELECT (record).height AS height")
    assert evaluate_scalar_expression(query.select[0].expression, {"record": None}) is None


def test_nested_member_chain_evaluates_recursively() -> None:
    row = {"record": {"dimensions": {"width": 1920, "height": 1080}}}
    query = _resolve("SELECT (record).dimensions.width AS width")
    assert evaluate_scalar_expression(query.select[0].expression, row) == 1920


def test_indexed_structured_element_can_be_followed_by_member_access() -> None:
    row = {"records": [{"height": 360}, {"height": 720}]}
    query = _resolve("SELECT records[1].height AS height")
    assert evaluate_scalar_expression(query.select[0].expression, row) == 720


def test_structure_preserving_function_result_can_be_evaluated() -> None:
    row = {"record": {"height": 720, "label": "preferred"}}
    query = _resolve("SELECT COALESCE(record, NULL).label AS label")
    assert evaluate_scalar_expression(query.select[0].expression, row) == "preferred"


def test_missing_dynamic_member_evaluates_to_sql_null() -> None:
    query = _resolve("SELECT (dynamic_record).provider_id AS provider_id")
    assert evaluate_scalar_expression(query.select[0].expression, {"dynamic_record": {}}) is None


def test_explicit_null_dynamic_member_remains_sql_null() -> None:
    query = _resolve("SELECT (dynamic_record).provider_id AS provider_id")
    row = {"dynamic_record": {"provider_id": None}}
    assert evaluate_scalar_expression(query.select[0].expression, row) is None


def test_runtime_non_dictionary_cannot_bypass_structured_type_boundary() -> None:
    class RecordLike:
        height = 720

    query = _resolve("SELECT (record).height AS height")
    assert evaluate_scalar_expression(query.select[0].expression, {"record": RecordLike()}) is None


def test_member_expression_participates_in_where_evaluation() -> None:
    records = [
        {"id": "a", "record": {"height": 720}},
        {"id": "b", "record": {"height": 1080}},
        {"id": "c", "record": None},
    ]
    query = _resolve("SELECT id WHERE (record).height = 720 ORDER BY id")
    assert [row["id"] for row in apply_query(records, query)] == ["a"]
