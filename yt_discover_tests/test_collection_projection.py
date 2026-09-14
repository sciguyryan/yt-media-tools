"""Collection projection semantics, typing and composition."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.query import (
    CollectionProjection,
    evaluate_scalar_expression,
    format_query,
    parse_query,
    resolve_query,
)
from yt_media_tools.query_model import QuerySyntaxError
from yt_media_tools.query_properties import analyse_expression
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


def test_map_projects_each_element_in_original_order() -> None:
    expression = _projection_expression("SELECT MAP(tags AS tag SELECT UPPER(tag)) AS upper_tags")
    assert isinstance(expression, CollectionProjection)
    assert evaluate_scalar_expression(expression, {"tags": ["a", None, "b"]}) == ["A", None, "B"]


def test_map_preserves_null_and_empty_collection_distinction() -> None:
    expression = _projection_expression("SELECT MAP(tags AS tag SELECT tag) AS copied")
    assert evaluate_scalar_expression(expression, {"tags": None}) is None
    assert evaluate_scalar_expression(expression, {"tags": []}) == []


def test_map_result_type_uses_projected_element_type_and_source_ordering() -> None:
    expression = _projection_expression("SELECT MAP(groups AS group SELECT group.target) AS targets")
    assert expression.resolved_type == QueryType.collection(
        QueryType.scalar("integer", nullable=False),
        nullable=False,
        ordering=CollectionOrdering.UNKNOWN,
    )


def test_map_preserves_source_collection_nullability() -> None:
    expression = _projection_expression("SELECT MAP(tags AS tag SELECT tag) AS copied")
    assert expression.resolved_type == QueryType.collection(
        QueryType.scalar("string", nullable=True),
        nullable=True,
        ordering=CollectionOrdering.STABLE,
    )


def test_map_stable_collection_can_be_indexed_after_projection() -> None:
    expression = _projection_expression("SELECT MAP(tags AS tag SELECT UPPER(tag))[1] AS second")
    assert evaluate_scalar_expression(expression, {"tags": ["a", "b", "c"]}) == "B"


def test_map_unknown_order_collection_does_not_invent_positional_semantics() -> None:
    try:
        _resolve("SELECT MAP(groups AS group SELECT group.target)[0] AS target")
    except QuerySyntaxError as exc:
        assert exc.message == "Collection indexing requires a stable logical collection ordering."
    else:
        raise AssertionError("Expected MAP over an unknown-order collection to remain non-indexable.")


def test_map_composes_with_filter_and_outer_row_fields() -> None:
    expression = _projection_expression(
        "SELECT MAP(FILTER(tags AS tag WHERE tag IS NOT NULL) AS tag SELECT title) AS titles"
    )
    assert evaluate_scalar_expression(
        expression,
        {"title": "x", "tags": [None, "x", "y", "x"]},
    ) == ["x", "x", "x"]
    assert analyse_expression(expression).required_fields == frozenset({"tags", "title"})


def test_map_supports_nested_scopes_and_outer_element_references() -> None:
    expression = _projection_expression(
        "SELECT MAP(groups AS group SELECT MAP(group.items AS item SELECT item.value + group.target)) AS adjusted"
    )
    groups = [
        {"target": 2, "items": [{"value": 1}, {"value": 3}]},
        {"target": 10, "items": None},
    ]
    assert evaluate_scalar_expression(expression, {"groups": groups}) == [[3, 5], None]


def test_map_can_project_structured_values_without_making_them_scalar() -> None:
    expression = _projection_expression("SELECT MAP(groups AS group SELECT group) AS copied")
    assert expression.resolved_type is not None
    assert expression.resolved_type.element_type == _group_type()
    groups = [{"target": 1, "items": []}]
    assert evaluate_scalar_expression(expression, {"groups": groups}) == groups


def test_map_can_project_nested_collection_values() -> None:
    expression = _projection_expression("SELECT MAP(groups AS group SELECT group.items) AS item_sets")
    assert expression.resolved_type is not None
    assert expression.resolved_type.element_type == _group_type().declared_member_type("items")
    groups = [
        {"target": 1, "items": [{"value": 4}]},
        {"target": 2, "items": None},
    ]
    assert evaluate_scalar_expression(expression, {"groups": groups}) == [[{"value": 4}], None]


def test_map_round_trips_canonically() -> None:
    sources = (
        "SELECT MAP(tags AS tag SELECT UPPER(tag)) AS upper_tags",
        "SELECT MAP(FILTER(tags AS tag WHERE tag IS NOT NULL) AS tag SELECT tag) AS kept",
        "SELECT MAP(groups AS group SELECT MAP(group.items AS item SELECT item.value + group.target)) AS adjusted",
    )
    for source in sources:
        formatted = format_query(parse_query(source))
        assert format_query(parse_query(formatted)) == formatted


def test_map_rejects_non_collection_operand_deterministically() -> None:
    try:
        _resolve("SELECT MAP(title AS item SELECT item) AS mapped")
    except QuerySyntaxError as exc:
        assert exc.message == "MAP requires a collection value; got string."
    else:
        raise AssertionError("Expected MAP over a scalar operand to be rejected.")


def test_map_remains_contextual_when_not_called() -> None:
    expression = parse_query("SELECT MAP AS value").select[0].expression
    assert expression is not None
    assert getattr(expression, "name", None) == "MAP"


def test_map_requires_explicit_binding_and_select_syntax() -> None:
    try:
        parse_query("SELECT MAP(tags tag SELECT tag) AS mapped")
    except QuerySyntaxError as exc:
        assert exc.message == "Expected AS after the MAP collection expression."
    else:
        raise AssertionError("Expected MAP without AS to be rejected.")

    try:
        parse_query("SELECT MAP(tags AS tag tag) AS mapped")
    except QuerySyntaxError as exc:
        assert exc.message == "Expected SELECT after the MAP element binding."
    else:
        raise AssertionError("Expected MAP without SELECT to be rejected.")


def test_map_rejects_aggregate_projection() -> None:
    try:
        _resolve("SELECT MAP(tags AS tag SELECT COUNT(*)) AS mapped")
    except QuerySyntaxError as exc:
        assert exc.message == "MAP projection cannot contain aggregate functions."
    else:
        raise AssertionError("Expected aggregate MAP projection to be rejected.")


def test_map_projection_is_optimiser_traversable() -> None:
    query = _resolve("SELECT MAP(tags AS tag SELECT tag) AS copied")
    optimised = optimise_query(query).query
    expression = optimised.select[0].expression
    assert isinstance(expression, CollectionProjection)
    assert evaluate_scalar_expression(expression, {"tags": ["a", "b"]}) == ["a", "b"]
