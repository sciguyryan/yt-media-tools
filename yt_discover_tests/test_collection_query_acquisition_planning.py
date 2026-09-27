"""Collection-query acquisition planning and pushdown coverage."""

from dataclasses import replace

from yt_media_tools import acquisition_plan as acquisition_plan_module
from yt_media_tools.acquisition_plan import STAGE_TAGS, plan_physical_acquisition
from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_metadata_requirements
from yt_media_tools.query import parse_query, resolve_query
from yt_media_tools.query_properties import CollectionQueryRequirement, analyse_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_capabilities import selected_facet_capabilities
from yt_media_tools.sources import resolve_source


def _resolved(query_text: str):
    records = [
        {
            "id": "a",
            "title": "keep",
            "tags": ["alpha", "skip", None],
        }
    ]
    return resolve_query(parse_query(query_text), QuerySchema(records), DateContext())


def test_collection_operations_produce_precise_semantic_requirements() -> None:
    source = resolve_source("@whatdamath")
    cases = {
        "SELECT id WHERE ANY(tags AS tag WHERE tag = 'alpha')": "any",
        "SELECT id WHERE ALL(tags AS tag WHERE tag IS NOT NULL)": "all",
        "SELECT CARDINALITY(tags)": "cardinality",
        "SELECT COUNT(tags AS tag WHERE tag IS NOT NULL)": "count",
        "SELECT FILTER(tags AS tag WHERE tag != 'skip')": "filter",
        "SELECT MAP(tags AS tag SELECT UPPER(tag))": "map",
    }

    for text, operation in cases.items():
        properties = analyse_query(_resolved(text), source=source)
        assert CollectionQueryRequirement("tags", operation) in properties.collection_query_requirements
        assert "tags" not in properties.whole_fields


def test_correlated_collection_query_records_outer_row_dependencies() -> None:
    source = resolve_source("@whatdamath")
    query = _resolved("SELECT COUNT(tags AS tag WHERE tag = title)")

    properties = analyse_query(query, source=source)

    assert properties.collection_query_requirements == (CollectionQueryRequirement("tags", "count", ("title",)),)
    assert properties.required_fields == frozenset({"tags", "title"})


def test_composed_filter_and_map_require_both_exact_operations() -> None:
    source = resolve_source("@whatdamath")
    query = _resolved("SELECT MAP(FILTER(tags AS tag WHERE tag != 'skip') AS kept SELECT UPPER(kept))")

    metadata = plan_metadata_requirements(query, source=source)

    assert metadata.collection_query_requirements == (
        CollectionQueryRequirement("tags", "filter"),
        CollectionQueryRequirement("tags", "map"),
    )
    assert "tags" not in metadata.whole_fields


def test_current_backend_falls_back_to_full_collection_acquisition() -> None:
    source = resolve_source("@whatdamath")
    requirement = CollectionQueryRequirement("tags", "filter")

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        collection_query_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.collection_queries == ()
    assert "full tags metadata is required" in stage.reason


def test_exact_backend_capability_permits_collection_query_pushdown(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_collection_query_fields=frozenset({"tags:filter"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = CollectionQueryRequirement("tags", "filter")

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        collection_query_requirements=(requirement,),
        whole_fields=frozenset(),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset()
    assert stage.collection_queries == (requirement,)
    assert "exact collection-query pushdown is permitted for: tags:filter" in stage.reason


def test_correlated_query_never_pushes_down_even_with_operation_capability(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_collection_query_fields=frozenset({"tags:count"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = CollectionQueryRequirement("tags", "count", ("title",))

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags", "title"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags", "title"}),
        collection_query_requirements=(requirement,),
        whole_fields=frozenset({"title"}),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.collection_queries == ()


def test_whole_collection_use_prevents_collection_query_pushdown(monkeypatch) -> None:
    source = resolve_source("@whatdamath")
    facet = selected_facet_capabilities(source)
    exact_facet = replace(facet, exact_collection_query_fields=frozenset({"tags:filter"}))
    monkeypatch.setattr(acquisition_plan_module, "selected_facet_capabilities", lambda _source: exact_facet)
    requirement = CollectionQueryRequirement("tags", "filter")

    plan = plan_physical_acquisition(
        source=source,
        required_fields=frozenset({"tags"}),
        enumeration_fields=frozenset(),
        detailed_fields=frozenset({"tags"}),
        collection_query_requirements=(requirement,),
        whole_fields=frozenset({"tags"}),
    )

    stage = plan.stage(STAGE_TAGS)
    assert stage.fields == frozenset({"tags"})
    assert stage.collection_queries == ()
