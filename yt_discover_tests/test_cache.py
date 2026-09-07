from datetime import datetime, timedelta, timezone
from pathlib import Path
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


def test_missing_dynamic_raw_path_forces_refresh(tmp_path: Path):
    path = tmp_path / "metadata.sqlite3"
    now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    with MetadataCache(path) as cache:
        cache.put_many("source", [{"id": "abc", "extra": {"score": 3}}], fetched_at=now)
        item = cache.get("source", "abc")
        assert item is not None
        assert cache.is_fresh(item, {"raw.extra.score"}, now=now)
        assert not cache.is_fresh(item, {"raw.extra.other"}, now=now)


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
