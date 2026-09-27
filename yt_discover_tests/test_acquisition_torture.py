"""Physical-planning torture coverage for optimiser/acquisition reconciliation."""

from __future__ import annotations

from datetime import datetime, timezone

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_query, plan_source_boundaries
from yt_media_tools.query import parse_query, query_physical_source_requests
from yt_media_tools.sources import resolve_source_request


DATES = DateContext(now=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc))


def _boundaries(text: str):
    query = parse_query(text)
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(source, facet=facet) for source, facet in requests)
    return plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DATES,
    )


def _single_plan(text: str):
    query = parse_query(text)
    source_name, facet = query_physical_source_requests(query)[0]
    source = resolve_source_request(source_name, facet=facet)
    return plan_query(query, source=source, dates=DATES)


def test_static_empty_branch_skips_every_acquisition_stage() -> None:
    plan = _single_plan("SELECT id FROM @whatdamath OF videos WHERE duration IS NULL AND duration IS NOT NULL")
    assert plan.acquisition.mode == "skip"
    assert plan.cost_class == "none"
    assert plan.physical_acquisition.required_stage_names == ()


def test_ordering_barrier_rejects_limit_enumeration_termination() -> None:
    plan = _single_plan(
        "SELECT id FROM @whatdamath OF videos WHERE title IS NOT NULL ORDER BY title DESC LIMIT 5 OFFSET 2"
    )
    assert not plan.limit_termination.eligible
    assert "ORDER BY" in plan.limit_termination.reason


def test_detailed_filter_keeps_limit_termination_on_detailed_match_path() -> None:
    plan = _single_plan("SELECT id FROM @whatdamath OF videos WHERE duration >= 10m LIMIT 5")
    assert plan.limit_termination.eligible
    assert plan.limit_termination.stops_detailed_acquisition
    assert not plan.limit_termination.stops_enumeration
    assert "complete-metadata" in plan.physical_acquisition.required_stage_names


def test_temporal_frontier_and_deferred_metadata_compose() -> None:
    plan = _single_plan(
        "SELECT duration FROM @whatdamath OF videos WHERE upload_date >= 2026-01-01 AND title = 'Example' LIMIT 5"
    )
    assert plan.acquisition.mode == "bounded-date"
    assert plan.temporal_bounds.for_field("upload_date") is not None
    assert plan.heuristics.information_value_tier == "high"
    assert "complete-metadata" in plan.heuristics.deferred_expensive_stages


def test_union_boundaries_keep_source_and_facet_identity_isolated() -> None:
    plans = _boundaries(
        "SELECT id FROM @whatdamath OF videos WHERE title = 'A' "
        "UNION ALL SELECT duration FROM @whatdamath OF shorts WHERE duration >= 10s"
    )
    assert [(plan.source_name, plan.facet) for plan in plans] == [
        ("@whatdamath", "videos"),
        ("@whatdamath", "shorts"),
    ]
    assert plans[0].metadata_requirements.requires_detailed_metadata is False
    assert plans[1].metadata_requirements.requires_detailed_metadata is True


def test_cte_dependency_pruning_reduces_physical_source_requirements() -> None:
    plans = _boundaries(
        "WITH rich AS (SELECT id, title, duration, view_count FROM @alpha "
        "WHERE upload_date >= 2026-01-01) "
        "SELECT id FROM rich"
    )
    assert len(plans) == 1
    assert plans[0].required_fields == frozenset({"id", "upload_date"})
    assert "duration" not in plans[0].required_fields
    assert "view_count" not in plans[0].required_fields


def test_reused_source_combines_requirements_without_inventing_safe_frontier() -> None:
    plans = _boundaries(
        "SELECT id FROM @alpha WHERE upload_date >= 2026-01-01 "
        "UNION ALL SELECT duration FROM @alpha WHERE title ILIKE '%science%'"
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan.use_count == 2
    assert plan.required_fields == frozenset({"id", "upload_date", "duration", "title"})
    assert plan.acquisition.mode == "full"
    assert plan.temporal_bounds.for_field("upload_date") is None


def test_dynamic_raw_requirement_is_not_treated_as_structurally_unavailable() -> None:
    plan = _single_plan("SELECT raw.extractor_specific FROM @alpha")
    assert "dynamic-raw" in plan.physical_acquisition.required_stage_names
    assert plan.metadata_requirements.requires_detailed_metadata
    assert plan.cost_class == "very-high"


def test_volatile_random_order_rejects_early_limit_termination() -> None:
    plan = _single_plan("SELECT id FROM @whatdamath OF videos ORDER BY RANDOM() LIMIT 3")
    assert not plan.limit_termination.eligible
    assert "volatile" in plan.limit_termination.reason.casefold() or "ORDER BY" in plan.limit_termination.reason
