"""Tests for the shared query language and dynamic schema."""

from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def resolved(source: str, records: list[dict], *, date_order: str = "dmy"):
    query = parse_query(source)
    schema = QuerySchema(records)
    return resolve_query(
        query,
        schema,
        DateContext(date_order=date_order, now=datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)),
    )


def test_example_query_with_iso_dates() -> None:
    records = [
        {"id": "a", "upload_date": "20240102", "duration": 1200, "view_count": 10_000, "live_status": "not_live"},
        {"id": "b", "upload_date": "20240103", "duration": 3600, "view_count": 50_000, "live_status": "not_live"},
    ]
    query = resolved(
        "WHERE upload_date BETWEEN 2024-01-01 AND 2024-12-31 "
        "AND duration < 45m AND views >= 5k "
        "AND live_status != 'is_upcoming' ORDER BY upload_date DESC",
        records,
    )
    assert [record["id"] for record in apply_query(records, query)] == ["a"]


def test_boolean_and_text_query() -> None:
    records = [
        {"id": "a", "title": "Feature", "duration": 300, "view_count": 200_000},
        {"id": "b", "title": "Trailer", "duration": 300, "view_count": 200_000},
    ]
    query = resolved(
        "WHERE (duration < 10m OR duration > 2h) AND views >= 100k AND NOT title CONTAINS 'trailer'",
        records,
    )
    assert [record["id"] for record in apply_query(records, query)] == ["a"]


def test_duration_word_units() -> None:
    records = [{"duration": 5400}, {"duration": 7200}, {"duration": 3600}]
    query = resolved("WHERE duration BETWEEN 90 minutes AND 2h", records)
    assert len(apply_query(records, query)) == 2


def test_local_named_and_relative_dates() -> None:
    records = [{"upload_date": "20240131"}, {"upload_date": "20260304"}, {"upload_date": "20200101"}]
    dmy = resolved("WHERE upload_date >= 31/01/2024", records)
    assert len(apply_query(records, dmy)) == 2
    named = resolved("WHERE upload_date >= 31 January 2024", records)
    assert len(apply_query(records, named)) == 2
    relative = resolved("WHERE upload_date >= 6 months ago", records)
    assert [r["upload_date"] for r in apply_query(records, relative)] == ["20260304"]


def test_mdy_date_option() -> None:
    records = [{"upload_date": "20240131"}]
    query = resolved("WHERE upload_date >= 01/31/2024", records, date_order="mdy")
    assert apply_query(records, query)


def test_timestamp_comparison() -> None:
    records = [{"release_timestamp": 1704067200}, {"release_timestamp": 1609459200}]
    query = resolved("WHERE release_timestamp >= 2024-01-01T00:00:00Z", records)
    assert apply_query(records, query) == [records[0]]


def test_dynamic_top_level_scalar() -> None:
    records = [{"channel_follower_count": 200_000}, {"channel_follower_count": 10_000}]
    query = resolved("WHERE channel_follower_count >= 100k", records)
    assert apply_query(records, query) == [records[0]]


def test_nested_raw_scalar() -> None:
    records = [
        normalise_record({"id": "a", "extra": {"score": 12}}),
        normalise_record({"id": "b", "extra": {"score": 4}}),
    ]
    query = resolved("WHERE raw.extra.score >= 10", records)
    assert [record["id"] for record in apply_query(records, query)] == ["a"]


def test_structured_raw_value_rejected() -> None:
    records = [normalise_record({"id": "a", "formats": [{"format_id": "1"}]})]
    with pytest.raises(QuerySyntaxError, match="structured"):
        resolved("WHERE raw.formats = 1", records)


def test_alias_resolves_to_canonical_field() -> None:
    records = [{"view_count": 20_000}]
    query = resolved("WHERE views >= 10k", records)
    assert apply_query(records, query)


def test_missing_values_sort_last() -> None:
    records = [{"id": "a", "view_count": 10}, {"id": "b", "view_count": None}, {"id": "c", "view_count": 20}]
    descending = resolved("ORDER BY views DESC", records)
    ascending = resolved("ORDER BY views ASC", records)
    assert [r["id"] for r in apply_query(records, descending)] == ["c", "a", "b"]
    assert [r["id"] for r in apply_query(records, ascending)] == ["a", "c", "b"]


def test_source_order_is_stable_tie_breaker() -> None:
    records = [
        {"id": "a", "upload_date": "20240101", "source_index": 1},
        {"id": "b", "upload_date": "20240101", "source_index": 2},
    ]
    query = resolved("ORDER BY upload_date DESC", records)
    assert [r["id"] for r in apply_query(records, query)] == ["a", "b"]


def test_unknown_field_suggests_dynamic_field() -> None:
    records = [{"view_count": 10}]
    query = parse_query("WHERE view_cout > 1")
    with pytest.raises(QuerySyntaxError, match="Did you mean"):
        resolve_query(query, QuerySchema(records))


def test_between_diagnostic_points_at_missing_and() -> None:
    with pytest.raises(QuerySyntaxError, match="Expected AND"):
        parse_query("WHERE duration BETWEEN 10m 2h")


def test_sql_doubled_quote_escape() -> None:
    records = [{"title": "Bob's video"}]
    query = resolved("WHERE title = 'Bob''s video'", records)
    assert apply_query(records, query)


def test_today_relative_calendar_arithmetic() -> None:
    records = [
        {"id": "inside", "upload_date": "20250903"},
        {"id": "boundary", "upload_date": "20250903"},
        {"id": "outside", "upload_date": "20250902"},
        {"id": "today", "upload_date": "20260903"},
    ]
    query = resolved("WHERE upload_date BETWEEN TODAY()-1yr AND TODAY()", records)
    assert [record["id"] for record in apply_query(records, query)] == ["inside", "boundary", "today"]


def test_today_month_arithmetic_clamps_calendar_day() -> None:
    context = DateContext(now=datetime(2024, 3, 31, 12, 0, tzinfo=timezone.utc))
    records = [{"upload_date": "20240229"}, {"upload_date": "20240228"}]
    query = resolve_query(parse_query("WHERE upload_date >= TODAY()-1mo"), QuerySchema(records), context)
    assert apply_query(records, query) == [records[0]]


def test_now_relative_elapsed_arithmetic() -> None:
    records = [
        {"id": "new", "release_timestamp": datetime(2026, 9, 3, 0, 0, tzinfo=timezone.utc).timestamp()},
        {"id": "old", "release_timestamp": datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc).timestamp()},
    ]
    query = resolved("WHERE release_timestamp >= NOW()-24h", records)
    assert [record["id"] for record in apply_query(records, query)] == ["new"]


def test_temporal_addition_is_supported() -> None:
    records = [{"upload_date": "20260910"}]
    query = resolved("WHERE upload_date <= TODAY()+1w", records)
    assert apply_query(records, query)


def test_now_rejected_for_date_field() -> None:
    records = [{"upload_date": "20260903"}]
    with pytest.raises(QuerySyntaxError, match=r"NOW\(\) produces a timestamp"):
        resolved("WHERE upload_date >= NOW()-1yr", records)


def test_today_rejected_for_timestamp_field() -> None:
    records = [{"release_timestamp": 1704067200}]
    with pytest.raises(QuerySyntaxError, match=r"TODAY\(\) produces a date"):
        resolved("WHERE release_timestamp >= TODAY()-1d", records)


def test_today_rejects_sub_day_arithmetic() -> None:
    records = [{"upload_date": "20260903"}]
    with pytest.raises(QuerySyntaxError, match="does not support hours"):
        resolved("WHERE upload_date >= TODAY()-3h", records)


def test_calendar_units_require_whole_numbers() -> None:
    records = [{"upload_date": "20260903"}]
    with pytest.raises(QuerySyntaxError, match="whole number"):
        resolved("WHERE upload_date >= TODAY()-1.5mo", records)


def test_enum_equality_is_case_insensitive() -> None:
    records = [{"id": "a", "live_status": "is_upcoming"}]
    query = resolved("WHERE live_status = 'IS_UPCOMING'", records)
    assert apply_query(records, query)


def test_enum_in_is_case_insensitive() -> None:
    records = [{"id": "a", "availability": "public"}]
    query = resolved("WHERE availability IN ('PRIVATE', 'PUBLIC')", records)
    assert apply_query(records, query)


def test_boolean_direct_predicates() -> None:
    records = [{"id": "a", "is_live": True}, {"id": "b", "is_live": False}]
    assert [r["id"] for r in apply_query(records, resolved("WHERE is_live", records))] == ["a"]
    assert [r["id"] for r in apply_query(records, resolved("WHERE NOT is_live", records))] == ["b"]


def test_negated_operators() -> None:
    records = [
        {"id": "a", "duration": 1200, "title": "Feature", "live_status": "not_live"},
        {"id": "b", "duration": 3600, "title": "Trailer", "live_status": "is_live"},
    ]
    query = resolved(
        "WHERE duration NOT BETWEEN 30m AND 2h "
        "AND title NOT CONTAINS 'trailer' "
        "AND live_status NOT IN ('is_live', 'is_upcoming')",
        records,
    )
    assert [r["id"] for r in apply_query(records, query)] == ["a"]


def test_date_context_captures_now_once() -> None:
    context = DateContext()
    assert context.now is not None
    assert context.local_now is context.now


def test_order_by_datetime_is_chronological_ascending_and_descending():
    records = [
        {"id": "late", "release_timestamp": 1767225600},
        {"id": "early", "release_timestamp": 1735689600},
        {"id": "middle", "release_timestamp": 1751328000},
    ]
    schema = QuerySchema(records)
    dates = DateContext()

    asc = resolve_query(parse_query("FROM @example ORDER BY release_timestamp ASC"), schema, dates)
    desc = resolve_query(parse_query("FROM @example ORDER BY release_timestamp DESC"), schema, dates)

    assert [item["id"] for item in apply_query(records, asc)] == ["early", "middle", "late"]
    assert [item["id"] for item in apply_query(records, desc)] == ["late", "middle", "early"]


def test_upload_date_then_release_timestamp_provides_chronological_subsort():
    records = [
        {"id": "same-day-late", "upload_date": "20260701", "release_timestamp": 1782896400},
        {"id": "same-day-early", "upload_date": "20260701", "release_timestamp": 1782871200},
        {"id": "next-day", "upload_date": "20260702", "release_timestamp": 1782950400},
    ]
    schema = QuerySchema(records)
    query = resolve_query(
        parse_query("FROM @example ORDER BY upload_date ASC, release_timestamp ASC"),
        schema,
        DateContext(),
    )
    assert [item["id"] for item in apply_query(records, query)] == ["same-day-early", "same-day-late", "next-day"]
