"""Compatibility checks for canonical legacy and current cache read statements."""

from __future__ import annotations

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_historical_cache_read_projection_and_order():
    with sqlite3.connect(":memory:") as db:
        db.executescript(
            """CREATE TABLE metadata_records (source_url TEXT, video_id TEXT, fetched_at TEXT, raw_json TEXT);
            CREATE TABLE source_entries (source_url TEXT, video_id TEXT, source_index INTEGER);
            INSERT INTO metadata_records VALUES ('src', 'b', '2020-01-02', '{}');
            INSERT INTO metadata_records VALUES ('src', 'a', '2020-01-01', '{}');
            INSERT INTO source_entries VALUES ('src', 'a', 0);
            """
        )
        row = db.execute(load_statement("cache_v3/record_by_source_and_id"), ("src", "a")).fetchone()
        assert row == ("2020-01-01", "{}")
        rows = db.execute(load_statement("cache_v3/source_records"), ("src",)).fetchall()
        assert [r[0] for r in rows] == ["a", "b"]
        assert db.execute(load_statement("cache_v3/count_source_records"), ("src",)).fetchone() == (2,)


def test_current_cache_read_order_and_success_filter():
    with sqlite3.connect(":memory:") as db:
        db.executescript(
            """CREATE TABLE cache_v4_sources (source_id INTEGER, source_url TEXT, facet TEXT);
            CREATE TABLE cache_v4_source_entries (source_id INTEGER, entity_id INTEGER, source_index INTEGER);
            CREATE TABLE cache_v4_media_entities (entity_id INTEGER, external_id TEXT);
            CREATE TABLE cache_v4_acquisition_state
                (entity_id INTEGER, provider_id INTEGER, acquisition_group_id INTEGER, last_success_at TEXT);
            CREATE TABLE cache_v4_providers (provider_id INTEGER, provider_key TEXT);
            CREATE TABLE cache_v4_acquisition_groups (acquisition_group_id INTEGER, group_key TEXT);
            INSERT INTO cache_v4_sources VALUES (1, 'src', '');
            INSERT INTO cache_v4_source_entries VALUES (1, 10, 1), (1, 11, 0);
            INSERT INTO cache_v4_media_entities VALUES (10, 'second'), (11, 'first');
            INSERT INTO cache_v4_providers VALUES (2, 'yt-dlp');
            INSERT INTO cache_v4_acquisition_groups VALUES (3, 'detailed');
            INSERT INTO cache_v4_acquisition_state VALUES (10, 2, 3, NULL), (11, 2, 3, '2020-01-01');
            """
        )
        rows = db.execute(load_statement("cache_v4/source_record_ids"), ("src",)).fetchall()
        assert rows == [("first",), ("second",)]
        assert db.execute(load_statement("cache_v4/count_detailed_source_records"), ("src",)).fetchone() == (1,)
