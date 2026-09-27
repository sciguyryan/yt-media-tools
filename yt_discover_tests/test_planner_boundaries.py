from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_query, required_query_fields
from yt_media_tools.query import parse_query
from yt_media_tools.query_properties import analyse_query
from yt_media_tools.sources import resolve_source_request


def test_semantic_properties_are_separate_from_source_policy():
    query = parse_query("SELECT title FROM @x WHERE view_count >= 10 LIMIT 2")
    properties = analyse_query(query)
    assert properties.required_fields == frozenset({"title", "view_count"})
    assert not properties.requires_aggregation
    assert properties.source is None
    assert required_query_fields(query) == {"title", "view_count"}


def test_source_aware_plan_combines_query_requirements_with_capabilities():
    query = parse_query("SELECT title FROM @x WHERE upload_date >= '2026-01-01' LIMIT 2")
    source = resolve_source_request("https://www.youtube.com/@example", source_type="channel", tab="all")
    plan = plan_query(query, source=source, dates=DateContext())
    assert plan.properties.source == source
    assert plan.acquisition.targeted
    assert plan.physical_request.source == source
    assert plan.physical_request.required_fields == frozenset({"title", "upload_date"})
    assert plan.physical_request.mode == "bounded-date"
    assert plan.limit_termination.eligible
    assert plan.cost_class == "moderate"


def test_generic_source_capabilities_are_available_without_changing_existing_limit_policy():
    query = parse_query("SELECT title FROM @x LIMIT 2")
    source = resolve_source_request("https://example.com/feed", source_type="auto", tab="all")
    plan = plan_query(query, source=source, dates=DateContext())
    assert plan.properties.source == source
    assert plan.properties.field_capability("title").field == "title"
    assert plan.limit_termination.eligible
