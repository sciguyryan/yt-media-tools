"""Final #130 tests for reduced v4 raw compatibility persistence."""

import json
from datetime import datetime, timezone

from yt_media_tools.cache import MetadataCache
from yt_media_tools.cache_v4_ytdlp import raw_compatibility_remainder


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_v4_raw_compatibility_omits_registered_scalars_and_keeps_unresolved_material() -> None:
    remainder = raw_compatibility_remainder(
        {
            "id": "abc",
            "title": "Example",
            "view_count": 7,
            "tags": ["one"],
            "extra": {"score": 3},
            "_yt_sql_source": "internal",
        }
    )
    assert "id" not in remainder
    assert "title" not in remainder
    assert "view_count" not in remainder
    assert "_yt_sql_source" not in remainder
    assert remainder == {"tags": ["one"], "extra": {"score": 3}}


def test_cache_write_persists_only_unresolved_remainder_in_v4(tmp_path) -> None:
    path = tmp_path / "cache.sqlite"
    record = {
        "id": "abc",
        "title": "Example",
        "duration": 12,
        "tags": ["one"],
        "extra": {"score": 3},
    }
    with MetadataCache(path) as cache:
        cache.put_many("source", [record], fetched_at=NOW)
        raw_json = (
            cache._db()
            .execute("SELECT raw_json FROM metadata_records WHERE source_url='source' AND video_id='abc'")
            .fetchone()[0]
        )
        payload_json = (
            cache._db()
            .execute(
                """
            SELECT payload_json FROM cache_v4_raw_compatibility
            WHERE source_url='source' AND video_id='abc'
            """
            )
            .fetchone()[0]
        )

    assert json.loads(raw_json) == record
    assert json.loads(payload_json) == {"tags": ["one"], "extra": {"score": 3}}


def test_v4_compatibility_payload_is_source_scoped(tmp_path) -> None:
    path = tmp_path / "cache.sqlite"
    with MetadataCache(path) as cache:
        cache.put_many("source-a", [{"id": "abc", "extra": {"score": 1}}], fetched_at=NOW)
        cache.put_many("source-b", [{"id": "abc", "extra": {"score": 2}}], fetched_at=NOW)
        rows = (
            cache._db()
            .execute(
                """
            SELECT source_url, payload_json FROM cache_v4_raw_compatibility
            WHERE video_id='abc' ORDER BY source_url
            """
            )
            .fetchall()
        )

    assert [(row[0], json.loads(row[1])["extra"]["score"]) for row in rows] == [
        ("source-a", 1),
        ("source-b", 2),
    ]
