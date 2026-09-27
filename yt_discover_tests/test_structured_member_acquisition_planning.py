"""Structured member acquisition planning coverage."""

from dataclasses import replace

from yt_media_tools import acquisition_plan as acquisition_plan_module
from yt_media_tools.acquisition_plan import STAGE_COMPLETE_METADATA, STAGE_FORMATS, plan_physical_acquisition
from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_metadata_requirements
from yt_media_tools.query import parse_query, resolve_query
from yt_media_tools.query_properties import IndexedFieldRequirement, StructuredMemberRequirement, analyse_query
from yt_media_tools.query_types import CollectionOrdering, QueryType, StructuredMember
from yt_media_tools.schema import FieldInfo, QuerySchema
from yt_media_tools.source_capabilities import selected_facet_capabilities
from yt_media_tools.sources import resolve_source


def _record_type() -> QueryType:
    return QueryType.structured(
        (
            StructuredMember("video", QueryType.structured((StructuredMember("height", QueryType.scalar("count")),))),
            StructuredMember("height", QueryType.scalar("count")),
        ),
        nullable=True,
    )


def test_direct_member_produces_precise_semantic_requirement() -> None:
    schema = QuerySchema.from_field_infos((FieldInfo("record", "structured", True, resolved_type=_record_type()),))
    query = resolve_query(parse_query("SELECT (record).video.height"), schema, DateContext())

    properties = analyse_query(query)

    assert properties.required_fields == frozenset({"record"})
    assert properties.member_requirements == (StructuredMemberRequirement("record", ("video", "height")),)
    assert properties.whole_fields == frozenset()


def test_indexed_member_combines_index_and_member_requirements() -> None:
    record_type = _record_type()
    schema = QuerySchema.from_field_infos(
        (
            FieldInfo(
                "items",
                "collection",
                True,
                resolved_type=QueryType.collection(record_type, ordering=CollectionOrdering.STABLE),
            ),
            FieldInfo("playlist_index", "count", True),
        )
    )
    constant = resolve_query(parse_query("SELECT items[0].height"), schema, DateContext())
    dynamic = resolve_query(parse_query("SELECT items[playlist_index].height"), schema, DateContext())

    assert analyse_query(constant).member_requirements == (StructuredMemberRequirement("items", ("height",), 0, True),)
    assert analyse_query(dynamic).member_requirements == (
        StructuredMemberRequirement("items", ("height",), None, True),
    )


def test_current_backend_falls_back_to_full_containing_collection() -> None:
    source = resolve_source("@whatdamath")
    requirement = StructuredMemberRequirement("formats", ("height",), 0, True)

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"formats"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"formats"}),
        member_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_FORMATS)
    assert stage.fields == frozenset({"formats"})
    assert stage.member_fields == ()
    assert "full formats metadata is required" in stage.reason


def test_exact_member_and_index_capabilities_permit_precise_member_acquisition(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(
        facet,
        exact_indexed_fields=frozenset({"formats"}),
        exact_member_fields=frozenset({"formats.height"}),
    )
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = StructuredMemberRequirement("formats", ("height",), 0, True)

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"formats"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"formats"}),
        member_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_FORMATS)
    assert stage.fields == frozenset()
    assert stage.indexed_fields == ()
    assert stage.member_fields == (requirement,)
    assert "exact structured member acquisition is permitted for: formats[0].height" in stage.reason


def test_exact_index_without_member_capability_acquires_the_containing_record(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_indexed_fields=frozenset({"formats"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    member = StructuredMemberRequirement("formats", ("height",), 0, True)

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"formats"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"formats"}),
        indexed_requirements=(IndexedFieldRequirement("formats", 0),),
        member_requirements=(member,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_FORMATS)
    assert stage.fields == frozenset()
    assert stage.indexed_fields == (IndexedFieldRequirement("formats", 0),)
    assert stage.member_fields == ()


def test_unknown_index_never_becomes_member_specific_acquisition(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(
        facet,
        exact_indexed_fields=frozenset({"formats"}),
        exact_member_fields=frozenset({"formats.height"}),
    )
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = StructuredMemberRequirement("formats", ("height",), None, True)

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"formats"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"formats"}),
        member_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_FORMATS)
    assert stage.fields == frozenset({"formats"})
    assert stage.member_fields == ()


def test_whole_structure_use_prevents_member_specific_acquisition(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_member_fields=frozenset({"record.height"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = StructuredMemberRequirement("record", ("height",))

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"record"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"record"}),
        member_requirements=(requirement,),
        whole_fields=frozenset({"record"}),
    )

    stage = plan.stage(STAGE_COMPLETE_METADATA)
    assert stage.fields == frozenset({"record"})
    assert stage.member_fields == ()


def test_metadata_requirement_plan_preserves_member_requirements() -> None:
    source = resolve_source("@whatdamath")
    schema = QuerySchema.from_field_infos((FieldInfo("record", "structured", True, resolved_type=_record_type()),))
    query = resolve_query(parse_query("SELECT (record).height"), schema, DateContext())

    metadata = plan_metadata_requirements(query, source=source)

    assert metadata.member_requirements == (StructuredMemberRequirement("record", ("height",)),)
