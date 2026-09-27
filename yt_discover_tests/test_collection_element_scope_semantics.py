"""Semantic foundation coverage for collection element scopes and quantifiers."""

from __future__ import annotations

import pytest

from yt_media_tools.collection_semantics import (
    bind_collection_element,
    existential_truth,
    universal_truth,
)
from yt_media_tools.query_types import CollectionOrdering, QueryType, StructuredMember


def test_collection_element_scope_preserves_exact_element_type() -> None:
    element_type = QueryType.structured(
        (StructuredMember("height", QueryType.scalar("count", nullable=False)),),
        nullable=True,
    )
    collection_type = QueryType.collection(
        element_type,
        nullable=False,
        ordering=CollectionOrdering.UNKNOWN,
    )

    scope = bind_collection_element(collection_type)

    assert scope.element_type == element_type
    assert scope.element_type.nullable is True
    assert scope.depth == 0
    assert scope.parent is None


def test_nested_collection_scopes_retain_lexical_outer_chain() -> None:
    outer_type = QueryType.collection(
        QueryType.scalar("string", nullable=False),
        nullable=False,
        ordering=CollectionOrdering.STABLE,
    )
    inner_type = QueryType.collection(
        QueryType.scalar("count", nullable=True),
        nullable=True,
        ordering=CollectionOrdering.STABLE,
    )

    outer = bind_collection_element(outer_type)
    inner = bind_collection_element(inner_type, parent=outer)

    assert inner.depth == 1
    assert inner.outer() is outer
    assert inner.element_type == QueryType.scalar("count", nullable=True)


def test_outer_scope_distance_is_explicit_and_bounded() -> None:
    collection = QueryType.collection(
        QueryType.scalar("string", nullable=False),
        ordering=CollectionOrdering.STABLE,
    )
    first = bind_collection_element(collection)
    second = bind_collection_element(collection, parent=first)
    third = bind_collection_element(collection, parent=second)

    assert third.outer(1) is second
    assert third.outer(2) is first
    with pytest.raises(LookupError):
        third.outer(3)
    for invalid in (0, -1, True, 1.5):
        with pytest.raises(ValueError):
            third.outer(invalid)  # type: ignore[arg-type]


def test_binding_rejects_non_collection_values() -> None:
    with pytest.raises(TypeError, match="is not a collection"):
        bind_collection_element(QueryType.scalar("string"))


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((), False),
        ((False,), False),
        ((None,), None),
        ((False, None), None),
        ((None, True), True),
        ((False, None, True), True),
    ],
)
def test_existential_truth_table(results: tuple[bool | None, ...], expected: bool | None) -> None:
    assert existential_truth(results) is expected


@pytest.mark.parametrize(
    ("results", "expected"),
    [
        ((), True),
        ((True,), True),
        ((None,), None),
        ((True, None), None),
        ((None, False), False),
        ((True, None, False), False),
    ],
)
def test_universal_truth_table(results: tuple[bool | None, ...], expected: bool | None) -> None:
    assert universal_truth(results) is expected


def test_null_collection_is_unknown_for_both_quantifiers() -> None:
    assert existential_truth((True,), collection_is_null=True) is None
    assert universal_truth((False,), collection_is_null=True) is None


def test_quantifier_reducers_validate_predicate_truth_values() -> None:
    with pytest.raises(TypeError, match="TRUE, FALSE or SQL NULL"):
        existential_truth((1,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="TRUE, FALSE or SQL NULL"):
        universal_truth(("yes",))  # type: ignore[arg-type]
