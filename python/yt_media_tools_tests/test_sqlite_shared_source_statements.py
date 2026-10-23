"""Verify shared cache-v4 source SQL using an actual SQLite database."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_source_statements_preserve_identity_observation_and_ordering():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE cache_v4_sources (
            source_id INTEGER PRIMARY KEY, source_url TEXT, source_kind TEXT, facet TEXT,
            UNIQUE(source_url, facet)
        );
        CREATE TABLE cache_v4_source_observations (
            source_id INTEGER PRIMARY KEY, last_observed_at TEXT, observed_entries INTEGER
        );
        CREATE TABLE cache_v4_source_entries (
            source_id INTEGER, entity_id INTEGER, source_index INTEGER
        );
        """
    )
    connection.execute(load_statement("cache_v4/source_upsert"), ("https://example.org", "channel", ""))
    connection.execute(load_statement("cache_v4/source_upsert"), ("https://example.org", "playlist", ""))
    source = connection.execute(load_statement("cache_v4/source_by_url_facet"), ("https://example.org", "")).fetchone()
    assert source == (1, "https://example.org", "playlist", "")
    connection.execute(load_statement("cache_v4/source_observation_upsert"), (1, "2026-01-01", 2))
    connection.execute(load_statement("cache_v4/source_observation_upsert"), (1, "2026-01-02", 3))
    assert connection.execute(load_statement("cache_v4/source_observation_by_id"), (1,)).fetchone() == ("2026-01-02", 3)
    connection.executemany(load_statement("cache_v4/source_entry_insert"), [(1, 5, 1), (1, 4, 0)])
    assert connection.execute(load_statement("cache_v4/source_entry_ids"), (1,)).fetchall() == [(4,), (5,)]
    connection.execute(load_statement("cache_v4/source_entries_delete"), (1,))
    assert connection.execute(load_statement("cache_v4/source_entry_ids"), (1,)).fetchall() == []
    connection.close()
