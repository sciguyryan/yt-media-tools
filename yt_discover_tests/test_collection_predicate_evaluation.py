"""Runtime semantics for existential and universal collection predicates."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.query import apply_query, evaluate, parse_query, resolve_query
from yt_media_tools.query_model import (
    CollectionElementReference,
    CollectionPredicate,
    QuerySyntaxError,
    ScalarComparison,
)
from yt_media_tools.query_types import CollectionOrdering, QueryType, StructuredMember
from yt_media_tools.schema import FieldInfo, QuerySchema


def _group_type() -> QueryType:
    item_type = QueryType.structured(
        (
            StructuredMember("value", QueryType.scalar("integer", nullable=True)),
            StructuredMember("score", QueryType.scalar("integer", nullable=True)),
        ),
        nullable=False,
    )
    return QueryType.structured(
        (
            StructuredMember("target", QueryType.scalar("integer", nullable=False)),
            StructuredMember("minimum", QueryType.scalar("integer", nullable=False)),
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
                    ordering=CollectionOrdering.STABLE,
                ),
            ),
        )
    )


def _resolve(source: str):
    return resolve_query(parse_query(source), _schema(), DateContext())


def _selected_ids(source: str, records: list[dict[str, object]]) -> list[str]:
    query = _resolve(source)
    return [row["id"] for row in apply_query(records, query)]


def test_any_selects_when_at_least_one_element_predicate_is_true() -> None:
    records = [
        {"id": "a", "tags": ["Music", "Astronomy"]},
        {"id": "b", "tags": ["Music"]},
    ]
    assert _selected_ids("SELECT id WHERE ANY(tags AS tag WHERE tag = 'Astronomy')", records) == ["a"]


def test_all_requires_every_element_predicate_to_be_true() -> None:
    records = [
        {"id": "a", "tags": ["Astronomy", "Astronomy"]},
        {"id": "b", "tags": ["Astronomy", "Music"]},
    ]
    assert _selected_ids("SELECT id WHERE ALL(tags AS tag WHERE tag = 'Astronomy')", records) == ["a"]


def test_empty_collection_uses_existential_false_and_vacuous_universal_true() -> None:
    records = [{"id": "empty", "tags": []}]
    assert _selected_ids("SELECT id WHERE ANY(tags AS tag WHERE tag = 'x')", records) == []
    assert _selected_ids("SELECT id WHERE ALL(tags AS tag WHERE tag = 'x')", records) == ["empty"]


def test_null_collection_produces_unknown_for_both_quantifiers() -> None:
    records = [{"id": "null", "tags": None}]
    assert _selected_ids("SELECT id WHERE ANY(tags AS tag WHERE tag = 'x')", records) == []
    assert _selected_ids("SELECT id WHERE ALL(tags AS tag WHERE tag = 'x')", records) == []


def test_unknown_element_predicates_follow_exact_three_valued_reduction() -> None:
    records = [
        {"id": "unknown-only", "tags": [None]},
        {"id": "any-true", "tags": [None, "x"]},
        {"id": "all-false", "tags": [None, "y"]},
    ]
    assert _selected_ids("SELECT id WHERE ANY(tags AS tag WHERE tag = 'x') ORDER BY id", records) == ["any-true"]
    assert _selected_ids("SELECT id WHERE ALL(tags AS tag WHERE tag = 'x') ORDER BY id", records) == []


def test_collection_predicate_can_compare_element_with_outer_row_field() -> None:
    records = [
        {"id": "a", "title": "Astronomy", "tags": ["Music", "Astronomy"]},
        {"id": "b", "title": "Science", "tags": ["Astronomy"]},
    ]
    assert _selected_ids("SELECT id WHERE ANY(tags AS tag WHERE tag = title)", records) == ["a"]


def test_nested_predicates_preserve_outer_collection_binding() -> None:
    records = [
        {
            "id": "a",
            "groups": [
                {"target": 2, "minimum": 5, "items": [{"value": 1, "score": 6}, {"value": 2, "score": 7}]},
                {"target": 9, "minimum": 3, "items": [{"value": 2, "score": 4}]},
            ],
        },
        {
            "id": "b",
            "groups": [{"target": 8, "minimum": 5, "items": [{"value": 2, "score": 7}]}],
        },
    ]
    query = "SELECT id WHERE ANY(groups AS group WHERE ANY(group.items AS item WHERE item.value = group.target))"
    assert _selected_ids(query, records) == ["a"]


def test_nested_all_composes_with_structured_members_and_null_nested_collection() -> None:
    records = [
        {"id": "a", "groups": [{"target": 1, "minimum": 5, "items": [{"score": 5}, {"score": 7}]}]},
        {"id": "b", "groups": [{"target": 1, "minimum": 5, "items": [{"score": 4}]}]},
        {"id": "c", "groups": [{"target": 1, "minimum": 5, "items": None}]},
    ]
    query = "SELECT id WHERE ANY(groups AS group WHERE ALL(group.items AS item WHERE item.score >= group.minimum))"
    assert _selected_ids(query, records) == ["a"]


def test_resolved_bound_element_retains_collection_element_type() -> None:
    query = _resolve("SELECT id WHERE ANY(tags AS tag WHERE tag = 'x')")
    assert isinstance(query.predicate, CollectionPredicate)
    assert isinstance(query.predicate.predicate, ScalarComparison)
    reference = query.predicate.predicate.left
    assert isinstance(reference, CollectionElementReference)
    assert reference.kind == "string"
    assert reference.resolved_type == QueryType.scalar("string", nullable=True)


def test_quantifier_rejects_non_collection_operand_deterministically() -> None:
    try:
        _resolve("SELECT id WHERE ANY(title AS item WHERE item = 'x')")
    except QuerySyntaxError as exc:
        assert exc.message == "ANY requires a collection value; got string."
    else:
        raise AssertionError("Expected ANY over a scalar operand to be rejected.")


def test_unknown_reduction_is_observable_before_where_filtering() -> None:
    any_query = _resolve("SELECT id WHERE ANY(tags AS tag WHERE tag = 'x')")
    all_query = _resolve("SELECT id WHERE ALL(tags AS tag WHERE tag = 'x')")
    assert evaluate(any_query.predicate, {"id": "a", "tags": [None]}) is None
    assert evaluate(all_query.predicate, {"id": "a", "tags": [None]}) is None
    assert evaluate(any_query.predicate, {"id": "a", "tags": None}) is None
    assert evaluate(all_query.predicate, {"id": "a", "tags": None}) is None
