"""Regression coverage for per-source/facet physical planning boundaries."""

from datetime import datetime, timezone

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_source_boundaries
from yt_media_tools.query import format_expression, parse_query, query_physical_source_requests
from yt_media_tools.sources import resolve_source_request


DATES = DateContext(now=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc))


def _plans(text: str):
    query = parse_query(text)
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(source, facet=facet) for source, facet in requests)
    return plan_source_boundaries(query, requests=requests, sources=sources, dates=DATES)


def test_union_sources_receive_independent_field_requirements() -> None:
    plans = _plans("SELECT id FROM @alpha WHERE title = 'A' UNION ALL SELECT id FROM @beta WHERE duration >= 10m")
    assert len(plans) == 2
    assert plans[0].source_name == "@alpha"
    assert plans[0].required_fields == frozenset({"id", "title"})
    assert plans[0].metadata_requirements.detailed_fields == frozenset()
    assert plans[1].source_name == "@beta"
    assert plans[1].required_fields == frozenset({"id", "duration"})
    assert plans[1].metadata_requirements.detailed_fields == frozenset({"duration"})


def test_same_source_reuse_unions_fields_and_ors_predicates() -> None:
    plans = _plans(
        "SELECT id FROM @alpha WHERE title = 'A' UNION ALL SELECT duration FROM @alpha WHERE upload_date >= 2026-04-01"
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan.use_count == 2
    assert plan.required_fields == frozenset({"id", "title", "duration", "upload_date"})
    assert plan.metadata_requirements.detailed_fields == frozenset({"duration", "upload_date"})
    assert plan.cost_class == "very-high"
    rendered = format_expression(plan.combined_predicate)
    assert "title = 'A'" in rendered
    assert "upload_date >= 2026-04-01" in rendered
    assert " OR " in rendered
    # One OR branch has no upload-date bound, so physical acquisition cannot use a date frontier.
    assert plan.temporal_bounds.for_field("upload_date") is None
    assert plan.acquisition.mode == "full"


def test_distinct_facets_of_same_channel_stay_separate_boundaries() -> None:
    plans = _plans(
        "SELECT id FROM @whatdamath OF videos WHERE upload_date >= 2026-04-01 "
        "UNION ALL SELECT id FROM @whatdamath OF shorts WHERE title ILIKE '%space%'"
    )
    assert len(plans) == 2
    assert (plans[0].source_name, plans[0].facet) == ("@whatdamath", "videos")
    assert plans[0].acquisition.mode == "bounded-date"
    assert plans[0].stable_order_field == "source_index"
    assert (plans[1].source_name, plans[1].facet) == ("@whatdamath", "shorts")
    assert plans[1].acquisition.mode == "full"


def test_cte_physical_sources_receive_outer_requirement_propagation() -> None:
    plans = _plans(
        "WITH recent AS (SELECT id, title FROM @alpha WHERE upload_date >= 2026-04-01), "
        "other AS (SELECT id FROM @beta) "
        "SELECT id FROM recent UNION ALL SELECT id FROM other"
    )
    assert len(plans) == 2
    assert plans[0].source_name == "@alpha"
    assert plans[0].required_fields == frozenset({"id", "upload_date"})
    assert plans[1].source_name == "@beta"
    assert plans[1].required_fields == frozenset({"id"})


def test_branch_plan_records_ordering_and_metadata_depth_independently() -> None:
    plans = _plans(
        "SELECT title FROM @alpha WHERE title ILIKE '%space%' "
        "UNION ALL SELECT duration FROM 'https://www.twitch.tv/example/videos' WHERE duration >= 10m"
    )
    assert plans[0].stable_order_field == "source_index"
    assert plans[0].metadata_requirements.requires_detailed_metadata is False
    assert plans[1].stable_order_field is None
    assert plans[1].metadata_requirements.requires_detailed_metadata is True
