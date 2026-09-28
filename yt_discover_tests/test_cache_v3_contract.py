"""Historical contract checks for the cache-v3 representation.

These tests freeze facts that the v3 -> v4 migration will have to understand. They
are intentionally about the implemented v3 representation, not the proposed v4 schema.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from yt_media_tools.cache import MetadataCache, SCHEMA_VERSION


def _table_sql(db: sqlite3.Connection, name: str) -> str:
    row = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    assert row is not None
    return str(row[0])


def test_v3_schema_keeps_source_state_physically_independent(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path):
        pass

    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone() == (
            str(SCHEMA_VERSION),
        )
        for table in (
            "metadata_records",
            "source_observations",
            "source_entries",
            "source_coverage",
            "source_frontiers",
        ):
            assert "FOREIGN KEY" not in _table_sql(db, table).upper()
    finally:
        db.close()


def test_v3_metadata_identity_is_source_scoped_and_raw_json_is_complete_record(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    when = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
    record = {"id": "same-id", "title": "Example", "extra": {"score": None}}

    with MetadataCache(path) as cache:
        assert cache.put_many("source-a", [record], fetched_at=when) == 1
        assert cache.put_many("source-b", [{**record, "title": "Other source"}], fetched_at=when) == 1

    db = sqlite3.connect(path)
    try:
        rows = db.execute(
            "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records ORDER BY source_url"
        ).fetchall()
    finally:
        db.close()

    assert len(rows) == 2
    assert rows[0][:3] == ("source-a", "same-id", when.isoformat())
    assert json.loads(rows[0][3]) == record
    assert rows[1][0:2] == ("source-b", "same-id")


def test_v3_source_entry_writer_replaces_complete_ordering_without_sql_cross_links(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        assert cache.record_source_entries("source", ["old-a", "old-b"]) == 2
        assert cache.record_source_entries("source", ["new-a", "new-b", "new-c"]) == 3
        assert cache.source_entry_ids("source") == ["new-a", "new-b", "new-c"]

    db = sqlite3.connect(path)
    try:
        assert db.execute(
            "SELECT video_id, source_index FROM source_entries WHERE source_url='source' ORDER BY source_index"
        ).fetchall() == [("new-a", 1), ("new-b", 2), ("new-c", 3)]
        assert db.execute("SELECT COUNT(*) FROM source_observations WHERE source_url='source'").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM source_frontiers WHERE source_url='source'").fetchone() == (0,)
    finally:
        db.close()


def test_v3_coverage_cached_entries_is_a_snapshot_not_a_live_count(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        cache.put_many("source", [{"id": "a"}, {"id": "b"}])
        cache.record_source_coverage("source", "channel", 2, complete=True, reason="complete")
        cache.put_many("source", [{"id": "c"}])
        coverage = cache.source_coverage("source")
        assert coverage is not None
        assert coverage.cached_entries == 2
        assert cache.count_source_records("source") == 3


def test_v3_observation_does_not_imply_entries_coverage_or_frontier(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    with MetadataCache(path) as cache:
        cache.record_source_observation("source", "channel", 7)
        assert cache.source_entry_ids("source") == []
        assert cache.source_coverage("source") is None
        assert cache.source_frontier("source") is None
