"""Protect the source-state read statement projections and ordering."""

import sqlite3

import pytest

from yt_media_tools.sqlite import load_statement


@pytest.mark.parametrize(
    ("name", "schema", "rows", "expected"),
    [
        (
            "cache_v3/source_entry_ids",
            "CREATE TABLE source_entries (source_url TEXT, video_id TEXT, source_index INTEGER)",
            [("source", "second", 2), ("source", "first", 1), ("other", "ignored", 0)],
            [("first",), ("second",)],
        ),
        (
            "cache_v3/source_frontier_by_url",
            "CREATE TABLE source_frontiers (source_url TEXT, source_kind TEXT, verified_at TEXT, known_entries INTEGER, head_video_id TEXT, overlap_confirmations INTEGER)",
            [("source", "channel", "2020-01-01", 2, "first", 1)],
            [("channel", "2020-01-01", 2, "first", 1)],
        ),
        (
            "cache_v3/source_coverage_by_url",
            "CREATE TABLE source_coverage (source_url TEXT, source_kind TEXT, observed_at TEXT, observed_entries INTEGER, cached_entries INTEGER, complete INTEGER, reason TEXT)",
            [("source", "channel", "2020-01-01", 2, 1, 0, "partial")],
            [("channel", "2020-01-01", 2, 1, 0, "partial")],
        ),
    ],
)
def test_v3_source_state_read_statements(name, schema, rows, expected):
    with sqlite3.connect(":memory:") as db:
        db.execute(schema)
        table = schema.split()[2]
        placeholders = ", ".join("?" for _ in rows[0])
        db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
        assert db.execute(load_statement(name), ("source",)).fetchall() == expected


def test_v4_frontier_and_coverage_reads_preserve_source_and_facet_filters():
    with sqlite3.connect(":memory:") as db:
        db.executescript("""
            CREATE TABLE cache_v4_sources (source_id INTEGER, source_url TEXT, source_kind TEXT, facet TEXT);
            CREATE TABLE cache_v4_media_entities (entity_id INTEGER, external_id TEXT);
            CREATE TABLE cache_v4_source_frontiers (source_id INTEGER, verified_at TEXT, known_entries INTEGER, head_entity_id INTEGER, overlap_confirmations INTEGER);
            CREATE TABLE cache_v4_source_coverage (source_id INTEGER, observed_at TEXT, observed_entries INTEGER, cached_entries INTEGER, complete INTEGER, reason TEXT);
            INSERT INTO cache_v4_sources VALUES (1, 'source', 'channel', '');
            INSERT INTO cache_v4_sources VALUES (2, 'source', 'channel', 'shorts');
            INSERT INTO cache_v4_media_entities VALUES (3, 'first');
            INSERT INTO cache_v4_source_frontiers VALUES (1, '2020-01-01', 2, 3, 1);
            INSERT INTO cache_v4_source_frontiers VALUES (2, '2020-01-02', 3, 3, 2);
            INSERT INTO cache_v4_source_coverage VALUES (1, '2020-01-01', 2, 1, 0, 'partial');
            INSERT INTO cache_v4_source_coverage VALUES (2, '2020-01-02', 3, 3, 1, 'complete');
        """)
        assert db.execute(load_statement("cache_v4/source_frontier_by_url"), ("source",)).fetchall() == [
            ("channel", "2020-01-01", 2, "first", 1)
        ]
        assert db.execute(load_statement("cache_v4/source_coverage_by_url"), ("source",)).fetchall() == [
            ("channel", "2020-01-01", 2, 1, 0, "partial")
        ]
