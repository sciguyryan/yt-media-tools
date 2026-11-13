"""Collection cardinality and predicate-qualified count semantics."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.query import (
    AggregateFunction,
    CollectionCount,
    format_query,
    parse_query,
    resolve_query,
)
from yt_media_tools.query_types import CollectionOrdering, QueryType
from yt_media_tools.schema import FieldInfo, QuerySchema


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
                "categories",
                "collection",
                False,
                resolved_type=QueryType.collection(
                    QueryType.scalar("string", nullable=False),
                    nullable=False,
                    ordering=CollectionOrdering.STABLE,
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


def test_cardinality_result_nullability_follows_collection_nullability() -> None:
    nullable = _projection_expression("SELECT CARDINALITY(tags) AS n")
    required = _projection_expression("SELECT CARDINALITY(categories) AS n")
    assert nullable.resolved_type == QueryType.scalar("integer", nullable=True)
    assert required.resolved_type == QueryType.scalar("integer", nullable=False)


def test_collection_count_and_cardinality_round_trip_canonically() -> None:
    sources = (
        "SELECT CARDINALITY(tags) AS n",
        "SELECT COUNT(tags AS tag WHERE tag = 'x') AS n",
        "SELECT id WHERE COUNT(tags AS tag WHERE tag IS NOT NULL) > 1",
    )
    for source in sources:
        formatted = format_query(parse_query(source))
        assert format_query(parse_query(formatted)) == formatted


def test_aggregate_count_remains_distinct_from_collection_count() -> None:
    aggregate = parse_query("SELECT COUNT(tags) AS n").select[0].expression
    collection = parse_query("SELECT COUNT(tags AS tag WHERE tag IS NOT NULL) AS n").select[0].expression
    assert isinstance(aggregate, AggregateFunction)
    assert isinstance(collection, CollectionCount)
