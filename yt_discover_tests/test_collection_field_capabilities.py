"""Collection-field schema, normalisation and capability integration coverage."""

from yt_media_tools.acquisition_plan import STAGE_CATEGORIES, STAGE_FORMATS, STAGE_TAGS, plan_physical_acquisition
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query_types import CollectionOrdering
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_capabilities import field_capability, selected_facet_capabilities
from yt_media_tools.sources import resolve_source


def test_known_multivalued_metadata_has_explicit_collection_types() -> None:
    schema = QuerySchema([normalise_record({"tags": ["zeta", "alpha"], "formats": [{"format_id": "1"}]})])

    tags = schema.resolve("tags")
    formats = schema.resolve("formats")
    assert tags is not None and tags.query_type.is_collection
    assert tags.query_type.element_type is not None
    assert tags.query_type.element_type.kind == "string"
    assert tags.query_type.ordering is CollectionOrdering.STABLE
    assert formats is not None and formats.query_type.is_collection
    assert formats.query_type.element_type is not None
    assert formats.query_type.element_type.kind == "structured"
    assert formats.query_type.ordering is CollectionOrdering.UNKNOWN


def test_scalar_taxonomy_collections_use_backend_independent_lexical_order() -> None:
    record = normalise_record(
        {
            "tags": ["Zulu", "alpha", "Beta"],
            "categories": ["Science", "Education", "Art"],
        }
    )

    assert record["tags"] == ["Beta", "Zulu", "alpha"]
    assert record["categories"] == ["Art", "Education", "Science"]
    assert record["_raw"]["tags"] == ["Zulu", "alpha", "Beta"]


def test_structured_collection_backend_order_is_not_promoted_to_logical_order() -> None:
    record = normalise_record(
        {
            "formats": [{"format_id": "late"}, {"format_id": "early"}],
            "chapters": [{"title": "B"}, {"title": "A"}],
            "thumbnails": [{"id": "2"}, {"id": "1"}],
        }
    )
    schema = QuerySchema([record])

    for name in ("formats", "chapters", "thumbnails"):
        field = schema.resolve(name)
        assert field is not None
        assert field.query_type.ordering is CollectionOrdering.UNKNOWN
        assert field.query_type.supports_positional_indexing is False


def test_source_capabilities_publish_collection_element_and_ordering_contracts() -> None:
    source = resolve_source("@whatdamath")
    logical_fields = {field.name: field for field in selected_facet_capabilities(source).logical_schema}

    assert logical_fields["tags"].query_type.ordering is CollectionOrdering.STABLE
    assert logical_fields["categories"].query_type.ordering is CollectionOrdering.STABLE
    assert logical_fields["formats"].query_type.ordering is CollectionOrdering.UNKNOWN
    assert field_capability("tags").logical_type == logical_fields["tags"].query_type
    assert field_capability("formats").logical_type == logical_fields["formats"].query_type


def test_first_class_collection_fields_route_to_collection_acquisition_stages() -> None:
    source = resolve_source("@whatdamath")
    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"id", "tags", "categories", "formats"}),
        enumeration_fields=frozenset({"id"}),
        detailed_fields=frozenset({"tags", "categories", "formats"}),
    )

    assert plan.stage(STAGE_TAGS).fields == frozenset({"tags"})
    assert plan.stage(STAGE_CATEGORIES).fields == frozenset({"categories"})
    assert plan.stage(STAGE_FORMATS).fields == frozenset({"formats"})
    assert not plan.stage("complete-metadata").required
