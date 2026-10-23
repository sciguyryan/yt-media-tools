"""Tests for the structured value type foundation used by yt-sql member access."""

import pytest

from yt_media_tools.query_types import (
    CollectionOrdering,
    QueryType,
    StructuredMember,
    StructuredShape,
)


def test_opaque_structured_type_preserves_existing_scalar_boundary() -> None:
    value_type = QueryType.scalar("structured", nullable=False)
    assert value_type == QueryType.structured_opaque(nullable=False)
    assert value_type.kind == "structured"
    assert value_type.is_structured is True
    assert value_type.structured_shape is StructuredShape.OPAQUE
    assert value_type.has_declared_members is False
    assert value_type.members == ()
    assert value_type.describe() == "structured"


def test_declared_structured_type_carries_named_member_types() -> None:
    value_type = QueryType.structured(
        (
            StructuredMember("height", QueryType.scalar("count", nullable=False)),
            StructuredMember("url", QueryType.scalar("string", nullable=True)),
        ),
        nullable=False,
    )
    assert value_type.structured_shape is StructuredShape.DECLARED
    assert value_type.has_declared_members is True
    assert value_type.declared_member_type("height") == QueryType.scalar("count", nullable=False)
    assert value_type.declared_member_type("url") == QueryType.scalar("string", nullable=True)
    assert value_type.declared_member_type("HEIGHT") is None
    assert value_type.declared_member_type("missing") is None
    assert value_type.describe() == "structured<declared>{height:count,url:string?}"


def test_dynamic_structured_type_is_distinct_from_declared_and_opaque_shapes() -> None:
    value_type = QueryType.structured(
        (StructuredMember("provider_id", QueryType.scalar("string", nullable=True)),),
        shape=StructuredShape.DYNAMIC,
    )
    assert value_type.structured_shape is StructuredShape.DYNAMIC
    assert value_type.has_declared_members is True
    assert value_type.declared_member_type("provider_id") == QueryType.scalar("string", nullable=True)
    assert value_type.describe() == "structured<dynamic>{provider_id:string?}?"


def test_structured_member_result_propagates_base_and_member_nullability() -> None:
    non_null_base = QueryType.structured(
        (
            StructuredMember("required", QueryType.scalar("string", nullable=False)),
            StructuredMember("optional", QueryType.scalar("string", nullable=True)),
        ),
        nullable=False,
    )
    nullable_base = non_null_base.with_nullable(True)

    assert non_null_base.member_result_type("required") == QueryType.scalar("string", nullable=False)
    assert non_null_base.member_result_type("optional") == QueryType.scalar("string", nullable=True)
    assert nullable_base.member_result_type("required") == QueryType.scalar("string", nullable=True)
    assert nullable_base.member_result_type("optional") == QueryType.scalar("string", nullable=True)
    assert nullable_base.member_result_type("missing") is None


def test_structured_members_compose_with_collection_and_nested_structured_types() -> None:
    dimensions = QueryType.structured(
        (
            StructuredMember("width", QueryType.scalar("count", nullable=False)),
            StructuredMember("height", QueryType.scalar("count", nullable=False)),
        ),
        nullable=False,
    )
    format_type = QueryType.structured(
        (
            StructuredMember("dimensions", dimensions),
            StructuredMember(
                "codecs",
                QueryType.collection(
                    QueryType.scalar("string", nullable=False),
                    nullable=False,
                    ordering=CollectionOrdering.STABLE,
                ),
            ),
        ),
        nullable=False,
    )
    formats = QueryType.collection(
        format_type,
        nullable=True,
        ordering=CollectionOrdering.UNKNOWN,
    )

    assert formats.element_type is format_type
    assert format_type.declared_member_type("dimensions") is dimensions
    codecs = format_type.declared_member_type("codecs")
    assert codecs is not None
    assert codecs.is_collection is True
    assert codecs.supports_positional_indexing is True


def test_structured_type_validates_shape_and_member_contracts() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        StructuredMember("", QueryType.scalar("string"))
    with pytest.raises(ValueError, match="unique"):
        QueryType.structured(
            (
                StructuredMember("value", QueryType.scalar("string")),
                StructuredMember("value", QueryType.scalar("count")),
            )
        )
    with pytest.raises(ValueError, match="structured_opaque"):
        QueryType.structured((), shape=StructuredShape.OPAQUE)
    with pytest.raises(ValueError, match="Opaque structured types cannot declare members"):
        QueryType(
            kind="structured",
            structured_shape=StructuredShape.OPAQUE,
            members=(StructuredMember("value", QueryType.scalar("string")),),
        )
    with pytest.raises(ValueError, match="Only structured types"):
        QueryType(
            kind="string",
            structured_shape=StructuredShape.DECLARED,
            members=(StructuredMember("value", QueryType.scalar("string")),),
        )
