"""Compatibility tests for stable raw spellings backed by registered metadata."""

from datetime import datetime, timezone

from yt_media_tools.acquisition_plan import STAGE_DYNAMIC_RAW
from yt_media_tools.dates import DateContext
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.query_evaluator import canonical_record_value
from yt_media_tools.schema import QuerySchema, raw_stable_field


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _resolve(text: str, records: list[dict]):
    return resolve_query(parse_query(text), QuerySchema(records), DateContext(now=NOW))


def test_simple_stable_raw_path_maps_to_logical_field() -> None:
    assert raw_stable_field("raw.title") == "title"
    assert raw_stable_field("RAW.views") == "view_count"
    assert raw_stable_field("raw.tags") is None
    assert raw_stable_field("raw.extra.score") is None


def test_stable_raw_scalar_resolves_without_raw_backend_payload() -> None:
    records = [{"id": "abc", "title": "Registered title"}]
    query = _resolve("SELECT raw.title AS title FROM @example", records)
    assert apply_query(records, query)[0]["title"] == "Registered title"


def test_stable_raw_alias_resolves_through_canonical_field() -> None:
    records = [{"id": "abc", "view_count": 42}]
    _resolve("SELECT raw.views AS views FROM @example", records)
    assert canonical_record_value(records[0], "raw.views", "count") == 42


def test_nested_raw_path_keeps_legacy_dynamic_semantics() -> None:
    records = [{"id": "abc", "_raw": {"extra": {"score": 7}}}]
    query = _resolve("SELECT raw.extra.score AS score FROM @example", records)
    assert apply_query(records, query)[0].get("score", 7) == 7


def test_registered_raw_scalar_no_longer_requires_dynamic_raw_stage() -> None:
    from yt_media_tools.planner import plan_query
    from yt_media_tools.sources import resolve_source_request

    query = parse_query("SELECT raw.duration FROM @example OF videos")
    plan = plan_query(
        query,
        source=resolve_source_request("@example", facet="videos"),
        dates=DateContext(now=NOW),
    )
    assert STAGE_DYNAMIC_RAW not in plan.physical_acquisition.required_stage_names
    assert "duration" in plan.physical_acquisition.stage("complete-metadata").fields
