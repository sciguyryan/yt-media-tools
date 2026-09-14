"""Collection cardinality and predicate-qualified count semantics."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.query import (
    AggregateFunction,
    CollectionCount,
    evaluate_scalar_expression,
    format_query,
    parse_query,
    resolve_query,
)
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_properties import analyse_expression
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


def test_cardinality_counts_all_elements_including_null_elements() -> None:
    expression = _projection_expression("SELECT CARDINALITY(tags) AS n")
    assert evaluate_scalar_expression(expression, {"tags": ["a", None, "b"]}) == 3
    assert evaluate_scalar_expression(expression, {"tags": []}) == 0
    assert evaluate_scalar_expression(expression, {"tags": None}) is None


def test_cardinality_result_nullability_follows_collection_nullability() -> None:
    nullable = _projection_expression("SELECT CARDINALITY(tags) AS n")
    required = _projection_expression("SELECT CARDINALITY(categories) AS n")
    assert nullable.resolved_type == QueryType.scalar("integer", nullable=True)
    assert required.resolved_type == QueryType.scalar("integer", nullable=False)


def test_collection_count_counts_only_true_predicate_results() -> None:
    expression = _projection_expression("SELECT COUNT(tags AS tag WHERE tag = 'x') AS n")
    assert isinstance(expression, CollectionCount)
    assert evaluate_scalar_expression(expression, {"tags": ["x", None, "y", "x"]}) == 2
    assert evaluate_scalar_expression(expression, {"tags": []}) == 0
    assert evaluate_scalar_expression(expression, {"tags": None}) is None


def test_collection_count_can_explicitly_count_null_elements() -> None:
    expression = _projection_expression("SELECT COUNT(tags AS tag WHERE tag IS NULL) AS n")
    assert evaluate_scalar_expression(expression, {"tags": ["x", None, None]}) == 2


def test_collection_count_can_reference_outer_row_fields() -> None:
    expression = _projection_expression("SELECT COUNT(tags AS tag WHERE tag = title) AS n")
    record = {"title": "x", "tags": ["x", "y", "x"]}
    assert evaluate_scalar_expression(expression, record) == 2
    properties = analyse_expression(expression)
    assert properties.required_fields == frozenset({"tags", "title"})


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


def test_cardinality_rejects_scalar_operand_deterministically() -> None:
    try:
        _resolve("SELECT CARDINALITY(title) AS n")
    except QuerySyntaxError as exc:
        assert exc.message == "CARDINALITY requires a collection value; got string."
    else:
        raise AssertionError("Expected CARDINALITY over a scalar operand to be rejected.")


def test_collection_count_rejects_scalar_operand_deterministically() -> None:
    try:
        _resolve("SELECT COUNT(title AS item WHERE item = 'x') AS n")
    except QuerySyntaxError as exc:
        assert exc.message == "Collection COUNT requires a collection value; got string."
    else:
        raise AssertionError("Expected collection COUNT over a scalar operand to be rejected.")
