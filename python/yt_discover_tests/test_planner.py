from datetime import datetime, timezone

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import APPROXIMATE_DATE_MARGIN_DAYS, plan_acquisition
from yt_media_tools.query import parse_query


def context():
    return DateContext(now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc))


def test_between_date_query_gets_bounded_plan_for_videos_tab():
    query = parse_query("FROM @example WHERE upload_date BETWEEN 2026-04-01 AND TODAY()")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.mode == "bounded-date"
    assert plan.lower_date_bound.isoformat() == "2026-04-01"
    assert (plan.lower_date_bound - plan.stop_before).days == APPROXIMATE_DATE_MARGIN_DAYS


def test_and_can_preserve_date_lower_bound():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01 AND views >= 10k")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.mode == "bounded-date"
    assert plan.lower_date_bound.isoformat() == "2026-04-01"


def test_or_without_date_bound_on_every_branch_forces_full_scan():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01 OR views >= 10k")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.mode == "full"


def test_or_with_date_bounds_on_both_branches_uses_earliest_bound():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01 OR upload_date >= 2026-06-01")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.mode == "bounded-date"
    assert plan.lower_date_bound.isoformat() == "2026-04-01"


def test_not_date_predicate_forces_full_scan():
    query = parse_query("FROM @example WHERE NOT upload_date >= 2026-04-01")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.mode == "full"


def test_playlist_never_uses_channel_date_order_assumption():
    query = parse_query("FROM PLabcdefghijk WHERE upload_date >= 2026-04-01")
    plan = plan_acquisition(query, source_kind="playlist", tab="all", dates=context())
    assert plan.mode == "full"


def test_all_tab_stays_full_to_preserve_existing_semantics():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01")
    plan = plan_acquisition(query, source_kind="channel", tab="all", dates=context())
    assert plan.mode == "full"


def test_stricter_and_date_bounds_choose_latest_lower_bound():
    query = parse_query("FROM @example WHERE upload_date >= 2026-04-01 AND upload_date >= 2026-05-01")
    plan = plan_acquisition(query, source_kind="channel", tab="videos", dates=context())
    assert plan.lower_date_bound.isoformat() == "2026-05-01"
