"""Parser and formatter coverage for scoped collection predicates."""

from __future__ import annotations

import pytest

from yt_media_tools.query import (
    CollectionElementReference,
    CollectionPredicate,
    ScalarComparison,
    ScalarMember,
)
from yt_media_tools.query_formatter import format_query
from yt_media_tools.query_model import Field, QuerySyntaxError
from yt_media_tools.query_parser import parse_query


def _predicate(source: str):
    return parse_query(source).predicate


def test_any_predicate_binds_scalar_collection_element() -> None:
    node = _predicate("FROM @fixture WHERE ANY(tags AS tag WHERE tag = 'Astronomy')")
    assert isinstance(node, CollectionPredicate)
    assert node.quantifier == "ANY"
    assert node.collection == Field("tags", 24)
    assert node.binding == "tag"
    assert isinstance(node.predicate, ScalarComparison)
    assert node.predicate.left == CollectionElementReference("tag", 0, 42)


def test_all_predicate_binds_structured_member_access() -> None:
    node = _predicate("FROM @fixture WHERE ALL(formats AS fmt WHERE fmt.height >= 720)")
    assert isinstance(node, CollectionPredicate)
    assert node.quantifier == "ALL"
    assert isinstance(node.predicate, ScalarComparison)
    assert isinstance(node.predicate.left, ScalarMember)
    assert node.predicate.left.member == "height"
    assert node.predicate.left.value == CollectionElementReference("fmt", 0, 45)


def test_nested_collection_predicate_can_reference_outer_binding() -> None:
    node = _predicate(
        "FROM @fixture WHERE ANY(groups AS group WHERE ANY(group.items AS item WHERE item.value = group.target))"
    )
    assert isinstance(node, CollectionPredicate)
    inner = node.predicate
    assert isinstance(inner, CollectionPredicate)
    assert isinstance(inner.collection, ScalarMember)
    assert inner.collection.value == CollectionElementReference("group", 0, 50)
    assert isinstance(inner.predicate, ScalarComparison)
    right = inner.predicate.right
    assert isinstance(right, ScalarMember)
    assert right.value == CollectionElementReference("group", 1, 89)


def test_inner_binding_shadows_same_named_outer_binding() -> None:
    node = _predicate("FROM @fixture WHERE ANY(groups AS item WHERE ANY(item.children AS item WHERE item.value = 1))")
    assert isinstance(node, CollectionPredicate)
    inner = node.predicate
    assert isinstance(inner, CollectionPredicate)
    assert isinstance(inner.collection, ScalarMember)
    assert inner.collection.value == CollectionElementReference("item", 0, 49)
    assert isinstance(inner.predicate, ScalarComparison)
    left = inner.predicate.left
    assert isinstance(left, ScalarMember)
    assert left.value.scope_distance == 0


def test_any_and_all_remain_contextual_identifiers_without_call_syntax() -> None:
    any_query = parse_query("FROM @fixture WHERE ANY = 1")
    all_query = parse_query("FROM @fixture WHERE ALL = 1")
    assert any_query.predicate.left == Field("ANY", 20)
    assert all_query.predicate.left == Field("ALL", 20)


def test_unbound_identifiers_remain_outer_query_fields() -> None:
    node = _predicate("FROM @fixture WHERE ANY(tags AS tag WHERE tag = title)")
    assert isinstance(node, CollectionPredicate)
    assert isinstance(node.predicate, ScalarComparison)
    assert node.predicate.right == Field("title", 48)


def test_collection_predicate_canonical_format_round_trip() -> None:
    source = (
        "SELECT id FROM @fixture WHERE ANY(groups AS group WHERE "
        "ALL(group.items AS item WHERE item.score >= group.minimum))"
    )
    canonical = format_query(parse_query(source))
    assert canonical == source
    assert format_query(parse_query(canonical)) == canonical


@pytest.mark.parametrize(
    ("source", "message"),
    (
        (
            "FROM @fixture WHERE ANY(tags tag WHERE tag = 'x')",
            "Expected AS to name the ANY element binding.",
        ),
        (
            "FROM @fixture WHERE ANY(tags AS raw.member WHERE raw.member = 'x')",
            "Collection element bindings must be simple identifiers.",
        ),
        (
            "FROM @fixture WHERE ANY(tags AS tag tag = 'x')",
            "Expected WHERE after the ANY element binding.",
        ),
    ),
)
def test_malformed_collection_predicate_diagnostics_are_deterministic(source: str, message: str) -> None:
    with pytest.raises(QuerySyntaxError) as exc_info:
        parse_query(source)
    assert exc_info.value.message == message
