from yt_media_tools.dates import DateContext
from yt_media_tools.planner import assess_cost, plan_acquisition, required_query_fields
from yt_media_tools.query import parse_query


def test_bounded_date_query_is_moderate():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=DateContext())
    cost, reason = assess_cost(query, plan)
    assert cost == "moderate"
    assert "safe source boundary" in reason


def test_dynamic_unbounded_query_is_very_high():
    query = parse_query("FROM @example WHERE raw.extra.score >= 10")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=DateContext())
    cost, reason = assess_cost(query, plan)
    assert cost == "very-high"
    assert "detailed metadata" in reason


def test_required_fields_include_projection_predicate_and_ordering():
    query = parse_query("SELECT id, title FROM @example WHERE views >= 10k ORDER BY upload_date DESC")
    fields = required_query_fields(query)
    assert {"id", "title", "views", "upload_date"} <= fields
