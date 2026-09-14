"""Stable member-schema coverage for first-class structured metadata collections."""

from __future__ import annotations

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query import QuerySyntaxError, parse_query, resolve_query
from yt_media_tools.query_types import CollectionOrdering, StructuredShape
from yt_media_tools.schema import QuerySchema


def _element_type(schema: QuerySchema, field_name: str):
    field = schema.resolve(field_name)
    assert field is not None
    assert field.query_type.is_collection
    assert field.query_type.element_type is not None
    return field.query_type, field.query_type.element_type


def test_format_metadata_has_closed_declared_member_schema() -> None:
    schema = QuerySchema([normalise_record({"formats": [{"format_id": "18"}]})])
    collection_type, element_type = _element_type(schema, "formats")

    assert collection_type.ordering is CollectionOrdering.UNKNOWN
    assert element_type.structured_shape is StructuredShape.DECLARED
    assert [member.name for member in element_type.members] == [
        "format_id",
        "ext",
        "width",
        "height",
        "resolution",
        "fps",
        "aspect_ratio",
        "vcodec",
        "acodec",
        "container",
        "protocol",
        "dynamic_range",
        "tbr",
        "vbr",
        "abr",
        "asr",
        "audio_channels",
        "filesize",
        "filesize_approx",
        "language",
        "format_note",
    ]
    assert element_type.declared_member_type("format_id").kind == "string"
    assert element_type.declared_member_type("height").kind == "count"
    assert element_type.declared_member_type("fps").kind == "number"
    assert element_type.declared_member_type("filesize").kind == "count"
    assert all(member.value_type.nullable for member in element_type.members)


def test_chapter_metadata_has_closed_declared_member_schema() -> None:
    schema = QuerySchema([normalise_record({"chapters": [{"title": "Intro"}]})])
    collection_type, element_type = _element_type(schema, "chapters")

    assert collection_type.ordering is CollectionOrdering.UNKNOWN
    assert element_type.structured_shape is StructuredShape.DECLARED
    assert [member.name for member in element_type.members] == ["title", "start_time", "end_time"]
    assert element_type.declared_member_type("title").kind == "string"
    assert element_type.declared_member_type("start_time").kind == "duration"
    assert element_type.declared_member_type("end_time").kind == "duration"
    assert all(member.value_type.nullable for member in element_type.members)


def test_thumbnail_metadata_has_closed_declared_member_schema() -> None:
    schema = QuerySchema([normalise_record({"thumbnails": [{"id": "0"}]})])
    collection_type, element_type = _element_type(schema, "thumbnails")

    assert collection_type.ordering is CollectionOrdering.UNKNOWN
    assert element_type.structured_shape is StructuredShape.DECLARED
    assert [member.name for member in element_type.members] == ["id", "url", "width", "height"]
    assert element_type.declared_member_type("id").kind == "string"
    assert element_type.declared_member_type("url").kind == "string"
    assert element_type.declared_member_type("width").kind == "count"
    assert element_type.declared_member_type("height").kind == "count"
    assert all(member.value_type.nullable for member in element_type.members)


def test_structured_metadata_schema_does_not_promote_backend_specific_members() -> None:
    schema = QuerySchema(
        [
            normalise_record(
                {
                    "formats": [
                        {
                            "format_id": "18",
                            "height": 360,
                            "provider_private_flag": "backend-only",
                        }
                    ]
                }
            )
        ]
    )
    _, element_type = _element_type(schema, "formats")

    assert element_type.declared_member_type("provider_private_flag") is None


def test_raw_structured_collection_elements_use_separate_dynamic_schema() -> None:
    schema = QuerySchema([normalise_record({"formats": [{"format_id": "18"}]})])
    raw_formats = schema.resolve_index_operand("raw.formats")

    assert raw_formats is not None
    assert raw_formats.query_type.is_collection
    assert raw_formats.query_type.element_type is not None
    assert raw_formats.query_type.element_type.structured_shape is StructuredShape.DYNAMIC
    assert raw_formats.query_type.element_type.declared_member_type("format_id") is not None


def test_declared_member_schema_does_not_change_structured_collection_ordering() -> None:
    schema = QuerySchema([normalise_record({"formats": [{"format_id": "18"}]})])

    with pytest.raises(
        QuerySyntaxError,
        match="Collection indexing requires a stable logical collection ordering\\.",
    ):
        resolve_query(parse_query("SELECT formats[0].height FROM @fixture"), schema, DateContext())
