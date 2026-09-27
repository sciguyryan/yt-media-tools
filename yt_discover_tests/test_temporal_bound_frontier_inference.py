"""Regression coverage for temporal-bound and acquisition-frontier inference."""

from datetime import datetime, timezone

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_acquisition
from yt_media_tools.query import parse_query
from yt_media_tools.temporal_bounds import infer_temporal_bounds, upload_date_frontier


DATES = DateContext(now=datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc))


def _bounds(query_text: str):
    return infer_temporal_bounds(parse_query(query_text).predicate, DATES)


def test_and_combines_strongest_upload_date_interval() -> None:
    plan = _bounds("FROM @example WHERE upload_date >= 2026-04-01 AND upload_date < 2026-05-01")
    bounds = plan.for_field("upload_date")
    assert bounds is not None
    assert bounds.lower is not None and bounds.lower.value.isoformat() == "2026-04-01"
    assert bounds.lower.inclusive
    assert bounds.upper is not None and bounds.upper.value.isoformat() == "2026-05-01"
    assert not bounds.upper.inclusive


def test_strict_date_lower_bound_advances_frontier_one_day() -> None:
    plan = _bounds("FROM @example WHERE upload_date > 2026-04-01")
    assert upload_date_frontier(plan).isoformat() == "2026-04-02"


def test_or_keeps_only_bound_implied_by_every_branch() -> None:
    plan = _bounds("FROM @example WHERE upload_date >= 2026-04-01 OR upload_date >= 2026-06-01")
    bounds = plan.for_field("upload_date")
    assert bounds is not None and bounds.lower is not None
    assert bounds.lower.value.isoformat() == "2026-04-01"


def test_or_with_unbounded_branch_refuses_temporal_frontier() -> None:
    plan = _bounds("FROM @example WHERE upload_date >= 2026-04-01 OR title = 'Space'")
    assert plan.for_field("upload_date") is None
    assert upload_date_frontier(plan) is None


def test_between_infers_both_timestamp_bounds_without_claiming_upload_frontier() -> None:
    plan = _bounds("FROM @example WHERE release_timestamp BETWEEN 2026-04-01T00:00:00Z AND 2026-05-01T00:00:00Z")
    bounds = plan.for_field("release_timestamp")
    assert bounds is not None
    assert bounds.lower is not None and bounds.lower.value.isoformat() == "2026-04-01T00:00:00+00:00"
    assert bounds.upper is not None and bounds.upper.value.isoformat() == "2026-05-01T00:00:00+00:00"
    assert upload_date_frontier(plan) is None


def test_in_list_infers_covering_temporal_interval() -> None:
    plan = _bounds("FROM @example WHERE upload_date IN (2026-04-03, 2026-04-01, 2026-04-02)")
    bounds = plan.for_field("upload_date")
    assert bounds is not None
    assert bounds.lower is not None and bounds.lower.value.isoformat() == "2026-04-01"
    assert bounds.upper is not None and bounds.upper.value.isoformat() == "2026-04-03"


def test_contradictory_interval_is_reported_without_unsafe_rewrite() -> None:
    plan = _bounds("FROM @example WHERE upload_date >= 2026-05-01 AND upload_date < 2026-04-01")
    bounds = plan.for_field("upload_date")
    assert bounds is not None and bounds.contradictory


def test_channel_videos_uses_inferred_upload_frontier() -> None:
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01")
    temporal = infer_temporal_bounds(query.predicate, DATES)
    acquisition = plan_acquisition(
        query,
        source_kind="channel",
        tab="videos",
        dates=DATES,
        temporal_bounds=temporal,
    )
    assert acquisition.mode == "bounded-date"
    assert acquisition.lower_date_bound.isoformat() == "2026-04-01"


def test_playlist_refuses_ordered_frontier_even_when_bound_exists() -> None:
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01")
    temporal = infer_temporal_bounds(query.predicate, DATES)
    acquisition = plan_acquisition(
        query,
        source_kind="playlist",
        tab="videos",
        dates=DATES,
        temporal_bounds=temporal,
    )
    assert acquisition.mode == "full"
