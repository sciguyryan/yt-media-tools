"""Registered collection persistence at the cache-v4 provider boundary."""

from datetime import datetime, timezone
import sqlite3

from yt_media_tools.cache import MetadataCache, initialise_v4_cache


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def test_fresh_v4_persists_only_declared_collections_and_registered_scalars(tmp_path) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    record = {
        "id": "abc",
        "title": "Example",
        "tags": ["two", "one"],
        "formats": [{"format_id": "18", "url": "https://example.invalid/transient"}],
        "extra": {"opaque": True},
    }

    with MetadataCache(path) as cache:
        assert cache.put_many("source", [record], fetched_at=NOW) == 1
        cached = cache.get("source", "abc")
        assert cached is not None
        assert cached.record["title"] == "Example"
        assert cached.record["tags"] == ["two", "one"]
        assert cached.record["formats"] == record["formats"]
        assert "extra" not in cached.record

        tables = {str(row[0]) for row in cache._db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "cache_v4_ytdlp_collections" in tables
        assert "cache_v4_raw_compatibility" not in tables
        assert "cache_v4_raw_migration_accounting" not in tables


def test_newer_registered_collection_state_replaces_older_state(tmp_path) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    with MetadataCache(path) as cache:
        cache.put_many("source-a", [{"id": "abc", "tags": ["old"], "chapters": [{"title": "old"}]}], fetched_at=NOW)
        cache.put_many("source-b", [{"id": "abc", "tags": [], "title": "new"}], fetched_at=NOW)
        cached = cache.get("source-a", "abc")
        assert cached is not None
        assert cached.record["tags"] == []
        assert "chapters" not in cached.record
        assert cached.record["title"] == "new"


def test_registered_collection_storage_has_no_open_ended_payload_column(tmp_path) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    connection = sqlite3.connect(path)
    try:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(cache_v4_ytdlp_collections)")}
    finally:
        connection.close()
    assert columns == {
        "entity_id",
        "tags_json",
        "categories_json",
        "formats_json",
        "chapters_json",
        "thumbnails_json",
    }


def test_fresh_v4_schema_contains_no_legacy_raw_compatibility_tables(tmp_path) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    connection = sqlite3.connect(path)
    try:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        connection.close()
    assert all(not name.startswith("cache_v4_raw_") for name in tables)
