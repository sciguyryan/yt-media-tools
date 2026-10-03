from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3

import pytest

from yt_media_tools.cache import MetadataCache, field_max_age


def test_cache_round_trip_and_fresh_hit(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with MetadataCache(path) as cache:
        assert cache.put_many("source", [{"id": "abc", "title": "Title", "view_count": 10}], fetched_at=now) == 1
        item = cache.get("source", "abc")
        assert item is not None
        assert item.record["title"] == "Title"
        assert cache.is_fresh(item, {"id", "title"}, now=now + timedelta(hours=1))


def test_cache_freshness_is_field_aware(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with MetadataCache(path) as cache:
        cache.put_many("source", [{"id": "abc", "upload_date": "20260701", "view_count": 10}], fetched_at=now)
        item = cache.get("source", "abc")
        assert item is not None
        later = now + timedelta(days=2)
        assert cache.is_fresh(item, {"upload_date"}, now=later)
        assert not cache.is_fresh(item, {"view_count"}, now=later)


def test_cache_is_source_scoped(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        cache.put_many("source-a", [{"id": "abc", "title": "A"}])
        assert cache.get("source-a", "abc") is not None
        assert cache.get("source-b", "abc") is None


def test_source_observation_alone_does_not_establish_trusted_frontier(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        cache.record_source_observation("source", "channel", 42)
        assert cache.source_frontier("source") is None
    db = sqlite3.connect(path)
    try:
        row = db.execute("SELECT observed_entries FROM source_observations WHERE source_url='source'").fetchone()
        assert row == (42,)
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "source_frontiers" in tables
    finally:
        db.close()


def test_unknown_schema_version_fails_closed(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('schema_version', '999')")
    db.commit()
    db.close()
    with (
        pytest.raises(RuntimeError, match="unsupported metadata-cache schema version"),
        MetadataCache(path),
    ):
        pass


def test_aliases_share_canonical_freshness_policy():
    assert field_max_age("views") == field_max_age("view_count")
    assert field_max_age("date") == field_max_age("upload_date")


def test_cache_get_many_batches_known_ids_and_preserves_source_scope(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    records = [{"id": f"video-{index:04d}", "title": f"Video {index}"} for index in range(1_001)]
    ids = [record["id"] for record in records]
    with MetadataCache(path) as cache:
        assert cache.put_many("source-a", records) == len(records)
        assert cache.put_many("source-b", [{"id": ids[0], "title": "Other source"}]) == 1
        statements: list[str] = []
        cache._db().set_trace_callback(statements.append)
        items = cache.get_many("source-a", [*ids, ids[0]])
        cache._db().set_trace_callback(None)

    assert len(items) == len(records)
    assert items[ids[0]].record["title"] == "Video 0"
    lookup_statements = [
        statement
        for statement in statements
        if "SELECT video_id, fetched_at, raw_json FROM metadata_records" in statement
    ]
    assert len(lookup_statements) == 2


def test_cache_get_many_ignores_missing_and_undecodable_rows(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        assert cache.put_many("source", [{"id": "good", "title": "Good"}]) == 1
        cache._db().execute(
            "INSERT INTO metadata_records(source_url, video_id, fetched_at, raw_json) VALUES(?, ?, ?, ?)",
            ("source", "bad", "not-a-time", "{}"),
        )
        items = cache.get_many("source", ["good", "bad", "missing"])

    assert set(items) == {"good"}


CACHE_V3_FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _copy_canonical_v3_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "canonical-valid-v3.sqlite3"
    shutil.copyfile(CACHE_V3_FIXTURE, path)
    return path


def test_canonical_v3_fixture_is_schema_3_and_readable(tmp_path: Path) -> None:
    path = _copy_canonical_v3_fixture(tmp_path)
    with MetadataCache(path) as cache:
        assert cache.get("https://www.youtube.com/@fixture/videos", "shared-video") is not None
        assert cache.get("https://www.youtube.com/@fixture/shorts", "shared-video") is not None

    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone() == ("3",)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    finally:
        db.close()


def test_canonical_v3_fixture_preserves_source_scoped_duplicate_media(tmp_path: Path) -> None:
    with MetadataCache(_copy_canonical_v3_fixture(tmp_path)) as cache:
        videos = cache.get("https://www.youtube.com/@fixture/videos", "shared-video")
        shorts = cache.get("https://www.youtube.com/@fixture/shorts", "shared-video")

    assert videos is not None and shorts is not None
    assert videos.record["title"] == "Shared from videos"
    assert shorts.record["title"] == "Shared from shorts"
    assert videos.record["duration"] == 0
    assert shorts.record["duration"] == 12
    assert videos.fetched_at != shorts.fetched_at


def test_canonical_v3_fixture_keeps_falsey_null_unicode_and_raw_material(tmp_path: Path) -> None:
    with MetadataCache(_copy_canonical_v3_fixture(tmp_path)) as cache:
        shared = cache.get("https://www.youtube.com/@fixture/videos", "shared-video")
        unicode_item = cache.get("https://www.youtube.com/@fixture/videos", "unicode-雪")
        null_item = cache.get("https://www.youtube.com/@fixture/videos", "null-fields")

    assert shared is not None and unicode_item is not None and null_item is not None
    assert shared.record["duration"] == 0
    assert shared.record["view_count"] == 0
    assert shared.record["availability"] is None
    assert shared.record["extra"] == {"score": 0, "note": None}
    assert shared.record["formats"][0]["url"].endswith("token=discard-me")
    assert unicode_item.record["title"] == "雪と星"
    assert unicode_item.record["uploader"] == "Δοκιμή"
    assert unicode_item.record["is_live"] is False
    assert unicode_item.record["tags"] == []
    assert null_item.record["title"] is None
    assert null_item.record["extra"]["nested"]["value"] is None


def test_canonical_v3_fixture_contains_valid_observation_only_state(tmp_path: Path) -> None:
    source = "https://example.invalid/enumeration-only"
    path = _copy_canonical_v3_fixture(tmp_path)
    with MetadataCache(path) as cache:
        assert cache.source_entry_ids(source) == []
        assert cache.source_coverage(source) is None
        assert cache.source_frontier(source) is None
        assert cache.count_source_records(source) == 0
    db = sqlite3.connect(path)
    try:
        assert db.execute(
            "SELECT source_kind, observed_entries FROM source_observations WHERE source_url = ?",
            (source,),
        ).fetchone() == ("url", 5)
    finally:
        db.close()


def test_canonical_v3_fixture_coverage_count_is_historical_snapshot(tmp_path: Path) -> None:
    source = "https://example.invalid/partial"
    with MetadataCache(_copy_canonical_v3_fixture(tmp_path)) as cache:
        coverage = cache.source_coverage(source)
        assert coverage is not None
        assert coverage.cached_entries == 1
        assert coverage.observed_entries == 4
        assert coverage.complete is False
        assert cache.count_source_records(source) == 2
