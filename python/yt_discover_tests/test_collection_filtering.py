"""Collection filtering semantics and type preservation."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.query import (
    AggregateFunction,
    evaluate_scalar_expression,
    format_query,
    parse_query,
    resolve_query,
)
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_types import CollectionOrdering, QueryType, StructuredMember
from yt_media_tools.schema import FieldInfo, QuerySchema


def _group_type() -> QueryType:
    item_type = QueryType.structured(
        (StructuredMember("value", QueryType.scalar("integer", nullable=True)),),
        nullable=False,
    )
    return QueryType.structured(
        (
            StructuredMember("target", QueryType.scalar("integer", nullable=False)),
            StructuredMember(
                "items",
                QueryType.collection(
                    item_type,
                    nullable=True,
                    ordering=CollectionOrdering.STABLE,
                ),
            ),
        ),
        nullable=False,
    )


def _schema() -> QuerySchema:
    return QuerySchema.from_field_infos(
        (
            FieldInfo("id", "string", False),
            FieldInfo("title", "string", True),
            FieldInfo(
                "tags",
                "collection",
                True,
                resolved_type=QueryType.collection(
                    QueryType.scalar("string", nullable=True),
                    nullable=True,
                    ordering=CollectionOrdering.STABLE,
                ),
            ),
            FieldInfo(
                "groups",
                "collection",
                False,
                resolved_type=QueryType.collection(
                    _group_type(),
                    nullable=False,
                    ordering=CollectionOrdering.UNKNOWN,
                ),
            ),
        )
    )


def _resolve(source: str):
    return resolve_query(parse_query(source), _schema(), DateContext())


def _projection_expression(source: str):
    query = _resolve(source)
    assert len(query.select) == 1
    assert query.select[0].expression is not None
    return query.select[0].expression


def test_filter_preserves_exact_collection_type_and_ordering_contract() -> None:
    expression = _projection_expression("SELECT FILTER(tags AS tag WHERE tag IS NOT NULL) AS kept")
    assert expression.resolved_type == QueryType.collection(
        QueryType.scalar("string", nullable=True),
        nullable=True,
        ordering=CollectionOrdering.STABLE,
    )


def test_filter_unknown_ordered_collection_does_not_invent_positional_semantics() -> None:
    try:
        _resolve("SELECT FILTER(groups AS group WHERE group.target > 0)[0].target AS target")
    except QuerySyntaxError as exc:
        assert exc.message == "Collection indexing requires a stable logical collection ordering."
    else:
        raise AssertionError("Expected filtered unknown-order collection indexing to remain rejected.")


def test_filter_composes_with_nested_quantifiers_and_structured_members() -> None:
    expression = _projection_expression(
        "SELECT FILTER(groups AS group WHERE ANY(group.items AS item WHERE item.value = group.target)) AS kept"
    )
    groups = [
        {"target": 2, "items": [{"value": 1}, {"value": 2}]},
        {"target": 8, "items": [{"value": 3}]},
        {"target": 4, "items": None},
    ]
    assert evaluate_scalar_expression(expression, {"groups": groups}) == [groups[0]]


def test_filter_round_trips_canonically() -> None:
    sources = (
        "SELECT FILTER(tags AS tag WHERE tag IS NOT NULL) AS kept",
        "SELECT FILTER(tags AS tag WHERE tag = title)[0] AS first",
        "SELECT FILTER(groups AS group WHERE ANY(group.items AS item WHERE item.value = group.target)) AS kept",
    )
    for source in sources:
        formatted = format_query(parse_query(source))
        assert format_query(parse_query(formatted)) == formatted


def test_filter_function_does_not_change_aggregate_filter_syntax() -> None:
    aggregate = parse_query("SELECT COUNT(*) FILTER (WHERE title IS NOT NULL) AS n").select[0].expression
    assert isinstance(aggregate, AggregateFunction)
    assert aggregate.filter_predicate is not None


def test_filter_remains_contextual_when_not_called() -> None:
    expression = parse_query("SELECT FILTER AS value").select[0].expression
    assert expression is not None
    assert getattr(expression, "name", None) == "FILTER"
