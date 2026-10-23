"""Precise collection-index acquisition planning coverage."""

from dataclasses import replace

from yt_media_tools import acquisition_plan as acquisition_plan_module
from yt_media_tools.acquisition_plan import STAGE_TAGS, plan_physical_acquisition
from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_metadata_requirements
from yt_media_tools.query import parse_query, resolve_query
from yt_media_tools.query_properties import IndexedFieldRequirement, analyse_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_capabilities import selected_facet_capabilities
from yt_media_tools.sources import resolve_source


def _resolved(source_text: str):
    records = [{"id": "a", "tags": ["alpha", "beta"], "playlist_index": 1}]
    return resolve_query(parse_query(source_text), QuerySchema(records), DateContext())


def test_constant_direct_index_produces_precise_semantic_requirement() -> None:
    source = resolve_source("@whatdamath")
    query = _resolved("SELECT tags[1] AS tag")

    properties = analyse_query(query, source=source)
    metadata = plan_metadata_requirements(query, source=source)

    assert properties.required_fields == frozenset({"tags"})
    assert properties.indexed_requirements == (IndexedFieldRequirement("tags", 1),)
    assert metadata.indexed_requirements == properties.indexed_requirements


def test_dynamic_index_retains_collection_requirement_without_false_precision() -> None:
    source = resolve_source("@whatdamath")
    query = _resolved("SELECT tags[playlist_index] AS tag")

    metadata = plan_metadata_requirements(query, source=source)

    assert IndexedFieldRequirement("tags", None) in metadata.indexed_requirements
    assert "tags" in metadata.detailed_fields


def test_current_backend_falls_back_to_full_collection_acquisition() -> None:
    source = resolve_source("@whatdamath")
    requirement = IndexedFieldRequirement("tags", 1)
    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        indexed_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.indexed_fields == ()
    assert "full tags metadata is required" in stage.reason


def test_exact_backend_capability_permits_indexed_acquisition(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_indexed_fields=frozenset({"tags"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)

    requirement = IndexedFieldRequirement("tags", 1)
    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        indexed_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset()
    assert stage.indexed_fields == (requirement,)
    assert "exact indexed acquisition is permitted for: tags[1]" in stage.reason


def test_dynamic_index_never_becomes_partial_even_with_backend_capability(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_indexed_fields=frozenset({"tags"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)

    requirement = IndexedFieldRequirement("tags", None)
    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        indexed_requirements=(requirement,),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.indexed_fields == ()


def test_whole_collection_use_prevents_partial_indexed_acquisition(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    query = _resolved("SELECT tags, tags[0] AS first_tag")
    metadata = plan_metadata_requirements(query, source=source)
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_indexed_fields=frozenset({"tags"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)

    assert "tags" in metadata.whole_fields
    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        indexed_requirements=metadata.indexed_requirements,
        whole_fields=metadata.whole_fields,
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.indexed_fields == ()
