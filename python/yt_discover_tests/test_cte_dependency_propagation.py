"""Regression coverage for backwards CTE dependency propagation."""

from datetime import datetime, timezone

from yt_media_tools.cte_dependencies import plan_cte_dependencies
from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_query, plan_source_boundaries
from yt_media_tools.query import parse_query, query_physical_source_requests
from yt_media_tools.sources import resolve_source_request


DATES = DateContext(now=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc))


def _boundary_plans(text: str):
    query = parse_query(text)
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(source, facet=facet) for source, facet in requests)
    return query, sources, plan_source_boundaries(query, requests=requests, sources=sources, dates=DATES)


def test_unused_cte_outputs_do_not_require_physical_metadata() -> None:
    query, _sources, plans = _boundary_plans(
        "WITH candidates AS ("
        "SELECT id, title, duration, view_count FROM @foo"
        ") SELECT id FROM candidates WHERE duration < 10m"
    )
    dependency = plan_cte_dependencies(query).for_cte("candidates")
    assert dependency is not None
    assert dependency.required_outputs == frozenset({"id", "duration"})
    assert dependency.input_fields == frozenset({"id", "duration"})
    assert dependency.pruned_outputs == frozenset({"title", "view_count"})
    assert plans[0].required_fields == frozenset({"id", "duration"})


def test_cte_internal_predicate_dependencies_are_always_retained() -> None:
    _query, _sources, plans = _boundary_plans(
        "WITH candidates AS ("
        "SELECT id, title, duration FROM @foo WHERE view_count > 1000"
        ") SELECT id FROM candidates WHERE duration < 10m"
    )
    assert plans[0].required_fields == frozenset({"id", "duration", "view_count"})


def test_cte_alias_dependency_maps_back_to_source_expression_fields() -> None:
    query, _sources, plans = _boundary_plans(
        "WITH candidates AS ("
        "SELECT id, LOWER(title) AS folded, duration FROM @foo"
        ") SELECT id FROM candidates WHERE folded = 'space'"
    )
    dependency = plan_cte_dependencies(query).for_cte("candidates")
    assert dependency is not None
    assert dependency.required_outputs == frozenset({"id", "folded"})
    assert dependency.input_fields == frozenset({"id", "title"})
    assert plans[0].required_fields == frozenset({"id", "title"})


def test_cte_requirements_propagate_through_an_intermediate_cte() -> None:
    query, _sources, plans = _boundary_plans(
        "WITH raw AS ("
        "SELECT id, title, duration, view_count FROM @foo"
        "), candidates AS ("
        "SELECT id, duration FROM raw WHERE title ILIKE '%space%'"
        ") SELECT id FROM candidates WHERE duration < 10m"
    )
    dependencies = plan_cte_dependencies(query)
    raw = dependencies.for_cte("raw")
    candidates = dependencies.for_cte("candidates")
    assert candidates is not None
    assert candidates.input_fields == frozenset({"id", "duration", "title"})
    assert raw is not None
    assert raw.required_outputs == frozenset({"id", "duration", "title"})
    assert raw.pruned_outputs == frozenset({"view_count"})
    assert plans[0].required_fields == frozenset({"id", "duration", "title"})


def test_distinct_cte_is_a_projection_pruning_barrier() -> None:
    query, _sources, plans = _boundary_plans(
        "WITH candidates AS (SELECT DISTINCT id, title, duration FROM @foo) SELECT id FROM candidates"
    )
    dependency = plan_cte_dependencies(query).for_cte("candidates")
    assert dependency is not None
    assert dependency.pruning_applied is False
    assert dependency.pruned_outputs == frozenset()
    assert plans[0].required_fields == frozenset({"id", "title", "duration"})


def test_volatile_cte_output_is_retained_even_when_not_consumed() -> None:
    query = parse_query("WITH candidates AS (SELECT id, RANDOM() AS shuffle_key FROM @foo) SELECT id FROM candidates")
    dependency = plan_cte_dependencies(query).for_cte("candidates")
    assert dependency is not None
    assert "shuffle_key" in dependency.retained_outputs
    assert "shuffle_key" not in dependency.pruned_outputs


def test_single_source_query_plan_uses_propagated_cte_physical_requirements() -> None:
    query = parse_query(
        "WITH candidates AS ("
        "SELECT id, title, duration, view_count FROM @foo"
        ") SELECT id FROM candidates WHERE duration < 10m"
    )
    source = resolve_source_request("@foo")
    plan = plan_query(query, source=source, dates=DATES)
    assert plan.physical_request.required_fields == frozenset({"id", "duration"})
    assert plan.physical_request.detailed_fields == frozenset({"duration"})


def test_union_cte_projection_remains_conservative() -> None:
    query = parse_query(
        "WITH candidates AS (SELECT id, title FROM @foo UNION ALL SELECT id, title FROM @bar) SELECT id FROM candidates"
    )
    dependency = plan_cte_dependencies(query).for_cte("candidates")
    assert dependency is not None
    assert dependency.pruning_applied is False
    assert dependency.pruned_outputs == frozenset()
