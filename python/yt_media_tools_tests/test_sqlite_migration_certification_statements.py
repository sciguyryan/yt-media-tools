"""Contracts for shared migration accounting and certification queries."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_migration_record_order_and_identity_projections():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE metadata_records (source_url TEXT, video_id TEXT, fetched_at TEXT, raw_json TEXT);"
        "CREATE TABLE source_entries (video_id TEXT);"
        "CREATE TABLE source_frontiers (head_video_id TEXT);"
        "CREATE TABLE cache_v4_media_entities (service TEXT, external_id TEXT);"
    )
    connection.executemany(
        "INSERT INTO metadata_records VALUES (?, ?, ?, ?)",
        [("b", "second", "2020-01-02", "{}"), ("a", "first", "2020-01-01", "{}")],
    )
    connection.execute("INSERT INTO source_entries VALUES ('entry')")
    connection.execute("INSERT INTO source_frontiers VALUES ('frontier')")
    connection.executemany(
        "INSERT INTO cache_v4_media_entities VALUES (?, ?)",
        [("youtube", "first"), ("other", "excluded")],
    )
    assert connection.execute(load_statement("cache_v3/migration_records_ordered")).fetchall() == [
        ("a", "first", "2020-01-01", "{}"),
        ("b", "second", "2020-01-02", "{}"),
    ]
    assert connection.execute(load_statement("cache_v3/migration_record_count")).fetchone() == (2,)
    assert connection.execute(load_statement("cache_v3/migration_record_video_ids")).fetchall() == [
        ("second",),
        ("first",),
    ]
    assert connection.execute(load_statement("cache_v3/migration_entry_video_ids")).fetchall() == [("entry",)]
    assert connection.execute(load_statement("cache_v3/migration_frontier_video_ids")).fetchall() == [("frontier",)]
    assert connection.execute(load_statement("cache_v4/migration_youtube_entity_ids")).fetchall() == [("first",)]
