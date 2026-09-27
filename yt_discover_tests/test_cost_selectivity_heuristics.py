"""Conservative cost and selectivity heuristics for physical planning."""

from yt_media_tools.acquisition_plan import (
    STAGE_COMPLETE_METADATA,
    STAGE_DYNAMIC_RAW,
)
from yt_media_tools.dates import DateContext
from yt_media_tools.discover_explain import explain_user_query, explain_user_query_json
from yt_media_tools.planner import plan_query
from yt_media_tools.query import format_expression, parse_query
from yt_media_tools.sources import resolve_source_request
from yt_media_tools.staged_predicates import plan_predicate_stages


def _source():
    return resolve_source_request("@example", facet="videos")


def test_enumeration_and_terms_are_ordered_by_information_value_per_cost() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE id != 'skip' AND title LIKE 'x%' AND title = 'x'")
    stages = plan_predicate_stages(query, source=_source())

    assert [format_expression(term) for term in stages.enumeration_terms] == [
        "title = 'x'",
        "title LIKE 'x%'",
        "id != 'skip'",
    ]
    assert [item.information_value for item in stages.enumeration_heuristics] == [
        "high",
        "moderate",
        "low",
    ]
    assert stages.heuristic_order_changed


def test_equally_ranked_enumeration_terms_keep_source_order() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE id = 'a' AND title = 'b'")
    stages = plan_predicate_stages(query, source=_source())

    assert [format_expression(term) for term in stages.enumeration_terms] == [
        "id = 'a'",
        "title = 'b'",
    ]
    assert not stages.heuristic_order_changed


def test_detailed_stage_is_deferred_behind_cheap_enumeration_filter() -> None:
    query = parse_query("SELECT duration FROM @example OF videos WHERE title = 'x'")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.heuristics.cost_tier == "very-high"
    assert plan.heuristics.selectivity_tier == "high"
    assert plan.heuristics.information_value_tier == "high"
    assert plan.heuristics.deferred_expensive_stages == (STAGE_COMPLETE_METADATA,)


def test_open_ended_raw_metadata_receives_very_high_cost_tier() -> None:
    query = parse_query("SELECT raw.extra.score FROM @example OF videos")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert STAGE_DYNAMIC_RAW in plan.physical_acquisition.required_stage_names
    assert plan.heuristics.cost_tier == "very-high"
    assert plan.heuristics.information_value_tier == "none"


def test_static_empty_boundary_has_no_cost_or_selectivity() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE view_count >= 10 AND view_count < 10")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.source_branch_eliminated
    assert plan.heuristics.cost_tier == "none"
    assert plan.heuristics.selectivity_tier == "none"
    assert plan.heuristics.information_value_tier == "none"


def test_human_explain_reports_predicate_and_boundary_heuristics() -> None:
    output = explain_user_query(
        "SELECT duration FROM @example WHERE title = 'x'",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    assert "Predicate cost/selectivity heuristics" in output
    assert "information-value=high" in output
    assert "Cost and selectivity heuristics" in output
    assert "Deferred until cheap filters survive: complete-metadata" in output


def test_json_explain_reports_heuristic_order_and_boundary_guidance() -> None:
    payload = explain_user_query_json(
        "SELECT duration FROM @example WHERE id != 'skip' AND title = 'x'",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    predicate = payload["predicate_stages"]
    assert predicate["heuristic_order_changed"] is True
    assert predicate["enumeration_heuristics"][0]["term"] == "title = 'x'"
    assert predicate["enumeration_heuristics"][0]["information_value"] == "high"

    boundary = payload["source_boundaries"][0]["heuristics"]
    assert boundary["cost_tier"] == "very-high"
    assert boundary["information_value_tier"] == "high"
    assert boundary["deferred_expensive_stages"] == [
        STAGE_COMPLETE_METADATA,
    ]


def test_heuristic_cost_tier_matches_existing_boundary_cost_class() -> None:
    queries = (
        "SELECT id FROM @example OF videos",
        "SELECT duration FROM @example OF videos",
        "SELECT id FROM @example OF videos WHERE upload_date >= 2026-01-01",
    )
    for query_text in queries:
        plan = plan_query(
            parse_query(query_text),
            source=_source(),
            dates=DateContext(),
        )
        assert plan.heuristics.cost_tier == plan.cost_class
