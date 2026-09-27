"""Compatibility checks for supported metadata-cache schema migrations."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from yt_media_tools.cache import MetadataCache, SCHEMA_VERSION


SOURCE = "https://www.youtube.com/@example/videos"


def test_v1_cache_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('schema_version', '1')")
    db.commit()
    db.close()
    with MetadataCache(path):
        pass
    db = sqlite3.connect(path)
    try:
        version = db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0]
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()
    assert version == str(SCHEMA_VERSION)
    assert "source_entries" in tables
    assert "source_coverage" in tables


def test_v2_cache_migrates_and_seeds_only_cardinality_matched_frontier(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('schema_version', '2')")
    db.execute(
        "CREATE TABLE source_observations (source_url TEXT PRIMARY KEY, source_kind TEXT NOT NULL, last_observed_at TEXT NOT NULL, observed_entries INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE source_entries (source_url TEXT NOT NULL, video_id TEXT NOT NULL, source_index INTEGER NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY (source_url, video_id))"
    )
    when = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO source_observations VALUES (?, 'channel', ?, 2)", (SOURCE, when))
    db.execute("INSERT INTO source_entries VALUES (?, 'newer', 1, ?)", (SOURCE, when))
    db.execute("INSERT INTO source_entries VALUES (?, 'older', 2, ?)", (SOURCE, when))
    db.commit()
    db.close()
    with MetadataCache(path) as cache:
        frontier = cache.source_frontier(SOURCE)
        assert frontier is not None
        assert frontier.known_entries == 2
        assert frontier.head_video_id == "newer"
    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0] == str(
            SCHEMA_VERSION
        )
    finally:
        db.close()
