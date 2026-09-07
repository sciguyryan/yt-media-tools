"""Tests for SELECT/FROM projection and serialisation."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from datetime import datetime, timezone

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.output import write_records
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema


def resolve(source: str, records: list[dict]):
    return resolve_query(
        parse_query(source),
        QuerySchema(records),
        DateContext(now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)),
    )


def capture(records: list[dict], query, output_format: str = "auto", *, explicit_select: bool = True) -> str:
    stream = io.StringIO()
    with redirect_stdout(stream):
        write_records(records, query, output_format, None, explicit_select=explicit_select)
    return stream.getvalue()


def test_complete_from_query_without_select_defaults_to_id() -> None:
    records = [{"id": "a", "upload_date": "20260401"}, {"id": "b", "upload_date": "20260331"}]
    query = resolve("FROM @channel WHERE upload_date >= 2026-04-01", records)
    selected = apply_query(records, query)
    assert capture(selected, query, explicit_select=False) == "a\n"


def test_select_single_field_defaults_to_lines() -> None:
    records = [{"id": "a", "title": "First"}, {"id": "b", "title": "Second"}]
    query = resolve("SELECT title FROM @channel ORDER BY id ASC", records)
    assert capture(apply_query(records, query), query) == "First\nSecond\n"


def test_select_multiple_fields_defaults_to_jsonl() -> None:
    records = [{"id": "a", "title": "First", "view_count": 1234}]
    query = resolve("SELECT id, title, views FROM @channel", records)
    assert capture(records, query) == '{"id": "a", "title": "First", "views": 1234}\n'


def test_select_alias_controls_output_name() -> None:
    records = [{"view_count": 1234}]
    query = resolve("SELECT view_count AS views FROM @channel", records)
    assert capture(records, query) == "1234\n"
    assert query.select[0].output_name == "views"


def test_select_nested_scalar() -> None:
    records = [{"id": "a", "_raw": {"extra": {"score": 12}}}]
    query = resolve("SELECT raw.extra.score AS score FROM @channel", records)
    assert capture(records, query) == "12\n"


def test_select_structured_value_rejected() -> None:
    records = [{"id": "a", "_raw": {"formats": [{"format_id": "1"}]}}]
    with pytest.raises(QuerySyntaxError, match="Cannot SELECT structured"):
        resolve("SELECT raw.formats FROM @channel", records)


def test_select_star_has_targeted_diagnostic() -> None:
    with pytest.raises(QuerySyntaxError, match=r"SELECT \*"):
        parse_query("SELECT * FROM @channel")


def test_quoted_url_source() -> None:
    query = parse_query("SELECT id FROM 'https://www.youtube.com/playlist?list=PLabc-def_123'")
    assert query.from_source == "https://www.youtube.com/playlist?list=PLabc-def_123"


def test_hyphenated_playlist_identifier_source() -> None:
    query = parse_query("FROM PLabc-def_123")
    assert query.from_source == "PLabc-def_123"


def test_csv_and_tsv_have_headers() -> None:
    records = [{"id": "a", "title": "First"}]
    query = resolve("SELECT id, title FROM @channel", records)
    assert capture(records, query, "csv") == "id,title\na,First\n"
    assert capture(records, query, "tsv") == "id\ttitle\na\tFirst\n"


def test_lines_rejects_multiple_fields() -> None:
    records = [{"id": "a", "title": "First"}]
    query = resolve("SELECT id, title FROM @channel", records)
    with pytest.raises(ValueError, match="exactly one"):
        capture(records, query, "lines")


def test_legacy_ids_format_rejects_explicit_select() -> None:
    records = [{"id": "a"}]
    query = resolve("SELECT id FROM @channel", records)
    with pytest.raises(ValueError, match="cannot be combined with SELECT"):
        capture(records, query, "ids")


def test_order_by_explicit_select_alias() -> None:
    records = [
        {"id": "a", "_raw": {"extra": {"score": 2}}},
        {"id": "b", "_raw": {"extra": {"score": 9}}},
    ]
    query = resolve("SELECT id, raw.extra.score AS score FROM @channel ORDER BY score DESC", records)
    assert [record["id"] for record in apply_query(records, query)] == ["b", "a"]
