"""Semantic resolution coverage for structured member access."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.query import (
    Field,
    QuerySyntaxError,
    ScalarFunction,
    ScalarIndex,
    ScalarMember,
    parse_query,
    resolve_query,
)
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
    return QuerySchema.from_field_infos(
        (
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
            FieldInfo("opaque", "structured", True, resolved_type=QueryType.structured_opaque()),
            FieldInfo("title", "string", True),
            FieldInfo("record.height", "count", False),
        )
    )


def _resolve(source: str, schema: QuerySchema | None = None):
    return resolve_query(parse_query(source), schema or _schema(), DateContext())


def test_member_access_resolves_declared_member_type_and_nullable_base() -> None:
    query = _resolve("SELECT (record).height AS height")
    expression = query.select[0].expression
    assert isinstance(expression, ScalarMember)
    assert expression.member == "height"
    assert expression.kind == "count"
    assert expression.resolved_type == QueryType.scalar("count", nullable=True)


def test_nested_member_access_resolves_structured_intermediate_type() -> None:
    query = _resolve("SELECT (record).dimensions.width AS width")
    outer = query.select[0].expression
    assert isinstance(outer, ScalarMember)
    assert isinstance(outer.value, ScalarMember)
    assert outer.value.member == "dimensions"
    assert outer.value.resolved_type is not None
    assert outer.value.resolved_type.is_structured is True
    assert outer.resolved_type == QueryType.scalar("count", nullable=True)


def test_indexed_structured_expression_can_resolve_a_member() -> None:
    query = _resolve("SELECT records[0].height AS height")
    expression = query.select[0].expression
    assert isinstance(expression, ScalarMember)
    assert isinstance(expression.value, ScalarIndex)
    assert expression.value.resolved_type is not None
    assert expression.value.resolved_type.is_structured is True
    assert expression.resolved_type == QueryType.scalar("count", nullable=True)


def test_structure_preserving_function_expression_can_resolve_a_member() -> None:
    query = _resolve("SELECT COALESCE(record, NULL).label AS label")
    expression = query.select[0].expression
    assert isinstance(expression, ScalarMember)
    assert isinstance(expression.value, ScalarFunction)
    assert expression.value.resolved_type is not None
    assert expression.value.resolved_type.is_structured is True
    assert expression.resolved_type == QueryType.scalar("string", nullable=True)


def test_known_dynamic_structured_member_can_be_resolved() -> None:
    dynamic_type = QueryType.structured(
        (StructuredMember("provider_id", QueryType.scalar("string", nullable=False)),),
        nullable=False,
        shape=StructuredShape.DYNAMIC,
    )
    schema = QuerySchema.from_field_infos(
        (FieldInfo("dynamic_record", "structured", False, resolved_type=dynamic_type),)
    )
    query = _resolve("SELECT (dynamic_record).provider_id AS provider_id", schema)
    expression = query.select[0].expression
    assert isinstance(expression, ScalarMember)
    assert expression.resolved_type == QueryType.scalar("string", nullable=False)


def test_unknown_declared_member_is_rejected_deterministically() -> None:
    with pytest.raises(QuerySyntaxError, match="Structured value has no member 'missing'\\."):
        _resolve("SELECT (record).missing")


def test_member_access_rejects_non_structured_operand_deterministically() -> None:
    with pytest.raises(
        QuerySyntaxError,
        match="Structured member access requires a structured value; got string\\.",
    ):
        _resolve("SELECT (title).height")


def test_member_access_rejects_opaque_structured_operand_until_schema_is_known() -> None:
    with pytest.raises(
        QuerySyntaxError,
        match="Structured member access requires a declared member schema; got opaque structured value\\.",
    ):
        _resolve("SELECT (opaque).height")


def test_bare_dotted_field_remains_distinct_from_postfix_member_access() -> None:
    query = _resolve("SELECT record.height")
    expression = query.select[0].expression
    assert isinstance(expression, Field)
    assert expression.name == "record.height"
    assert expression.kind == "count"
