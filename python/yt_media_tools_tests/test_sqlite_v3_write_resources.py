"""Behavioural contracts for historical cache-v3 write resources."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_metadata_upsert_replaces_existing_record():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE metadata_records (source_url TEXT, video_id TEXT, fetched_at TEXT, raw_json TEXT, PRIMARY KEY (source_url, video_id))"
    )
    sql = load_statement("cache_v3/upsert_metadata_record")
    db.execute(sql, ("source", "id", "old", "{}"))
    db.execute(sql, ("source", "id", "new", '{"a": 1}'))
    assert db.execute("SELECT fetched_at, raw_json FROM metadata_records").fetchall() == [("new", '{"a": 1}')]


def test_source_entry_insert_preserves_order_and_observation():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE source_entries (source_url TEXT, video_id TEXT, source_index INTEGER, observed_at TEXT)")
    db.executemany(load_statement("cache_v3/insert_source_entry"), [("s", "b", 1, "time"), ("s", "a", 2, "time")])
    assert db.execute(
        "SELECT video_id, source_index, observed_at FROM source_entries ORDER BY source_index"
    ).fetchall() == [("b", 1, "time"), ("a", 2, "time")]


def test_frontier_observation_and_coverage_upserts_preserve_scope():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE source_frontiers (source_url TEXT PRIMARY KEY, source_kind TEXT, verified_at TEXT, known_entries INTEGER, head_video_id TEXT, overlap_confirmations INTEGER);
        CREATE TABLE source_observations (source_url TEXT PRIMARY KEY, source_kind TEXT, last_observed_at TEXT, observed_entries INTEGER);
        CREATE TABLE source_coverage (source_url TEXT PRIMARY KEY, source_kind TEXT, observed_at TEXT, observed_entries INTEGER, cached_entries INTEGER, complete INTEGER, reason TEXT);
    """)
    frontier = load_statement("cache_v3/upsert_source_frontier")
    observation = load_statement("cache_v3/upsert_source_observation")
    coverage = load_statement("cache_v3/upsert_source_coverage")
    for source in ("one", "two"):
        db.execute(frontier, (source, "kind", "old", 2, "first", 1))
        db.execute(observation, (source, "kind", "old", 2))
        db.execute(coverage, (source, "kind", "old", 2, 1, 0, "partial"))
    db.execute(frontier, ("one", "newkind", "new", 3, "second", 2))
    db.execute(observation, ("one", "newkind", "new", 3))
    db.execute(coverage, ("one", "newkind", "new", 3, 3, 1, "complete"))
    assert db.execute(
        "SELECT source_kind, verified_at, known_entries, head_video_id, overlap_confirmations FROM source_frontiers WHERE source_url = 'one'"
    ).fetchone() == ("newkind", "new", 3, "second", 2)
    assert db.execute(
        "SELECT source_kind, last_observed_at, observed_entries FROM source_observations WHERE source_url = 'one'"
    ).fetchone() == ("newkind", "new", 3)
    assert db.execute(
        "SELECT source_kind, observed_at, observed_entries, cached_entries, complete, reason FROM source_coverage WHERE source_url = 'one'"
    ).fetchone() == ("newkind", "new", 3, 3, 1, "complete")
    assert db.execute(
        "SELECT source_kind, observed_entries FROM source_observations WHERE source_url = 'two'"
    ).fetchone() == ("kind", 2)
