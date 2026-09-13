"""Tests for the collection type contract introduced for yt-sql indexing."""

import pytest

from yt_media_tools.query_types import CollectionOrdering, QueryType
from yt_media_tools.schema import FieldInfo


def test_scalar_type_retains_existing_kind_and_nullability() -> None:
    value_type = QueryType.scalar("string", nullable=False)
    assert value_type.kind == "string"
    assert value_type.nullable is False
    assert value_type.is_collection is False
    assert value_type.describe() == "string"


def test_collection_requires_declared_element_type_and_ordering() -> None:
    with pytest.raises(ValueError, match="element type"):
        QueryType(kind="collection", ordering=CollectionOrdering.STABLE)
    with pytest.raises(ValueError, match="ordering"):
        QueryType(kind="collection", element_type=QueryType.scalar("string"))


def test_non_collection_rejects_collection_metadata() -> None:
    with pytest.raises(ValueError, match="Only collection types"):
        QueryType(kind="string", element_type=QueryType.scalar("string"))


def test_stable_collection_supports_zero_based_positional_contract() -> None:
    collection = QueryType.collection(
        QueryType.scalar("string", nullable=False),
        nullable=False,
        ordering=CollectionOrdering.STABLE,
    )
    assert collection.supports_positional_indexing is True
    assert collection.describe() == "collection<string>[stable]"


def test_unknown_or_unordered_collection_has_no_positional_contract() -> None:
    element = QueryType.scalar("string")
    unknown = QueryType.collection(element, ordering=CollectionOrdering.UNKNOWN)
    unordered = QueryType.collection(element, ordering=CollectionOrdering.UNORDERED)
    assert unknown.supports_positional_indexing is False
    assert unordered.supports_positional_indexing is False
    with pytest.raises(TypeError, match="stable logical collection ordering"):
        unknown.indexed_result_type()
    with pytest.raises(TypeError, match="stable logical collection ordering"):
        unordered.indexed_result_type()


def test_index_result_is_nullable_even_for_non_null_elements() -> None:
    collection = QueryType.collection(
        QueryType.scalar("integer", nullable=False),
        nullable=False,
        ordering=CollectionOrdering.STABLE,
    )
    result = collection.indexed_result_type()
    assert result == QueryType.scalar("integer", nullable=True)


def test_collection_elements_may_themselves_be_nullable() -> None:
    collection = QueryType.collection(
        QueryType.scalar("string", nullable=True),
        ordering=CollectionOrdering.STABLE,
    )
    assert collection.element_type == QueryType.scalar("string", nullable=True)
    assert collection.indexed_result_type().nullable is True


def test_field_info_exposes_scalar_query_type_without_changing_existing_fields() -> None:
    info = FieldInfo("title", "string", True)
    assert info.query_type == QueryType.scalar("string", nullable=True)


def test_field_info_can_carry_complete_collection_type() -> None:
    collection_type = QueryType.collection(
        QueryType.scalar("string", nullable=False),
        nullable=True,
        ordering=CollectionOrdering.STABLE,
    )
    info = FieldInfo("tags", "collection", True, resolved_type=collection_type)
    assert info.query_type is collection_type


def test_field_info_rejects_inconsistent_resolved_type() -> None:
    with pytest.raises(ValueError, match="Field kind"):
        FieldInfo("tags", "collection", True, resolved_type=QueryType.scalar("string"))
    with pytest.raises(ValueError, match="NULLability"):
        FieldInfo("title", "string", False, resolved_type=QueryType.scalar("string", nullable=True))
