"""Exercise the shared SQLite cache lifecycle statement contracts."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_cache_version_statements() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute(load_statement("common/cache_insert_schema_version"), ("3",))
    db.execute(load_statement("common/cache_set_schema_version"), ("4",))
    assert db.execute("SELECT value FROM cache_meta WHERE key = 'schema_version'").fetchone() == ("4",)


def test_source_cleanup_statements() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE source_entries (source_url TEXT)")
    db.execute("CREATE TABLE source_frontiers (source_url TEXT)")
    db.execute("CREATE TABLE cache_v4_source_frontiers (source_id INTEGER)")
    db.executemany("INSERT INTO source_entries VALUES (?)", [("a",), ("b",)])
    db.executemany("INSERT INTO source_frontiers VALUES (?)", [("a",), ("b",)])
    db.executemany("INSERT INTO cache_v4_source_frontiers VALUES (?)", [(1,), (2,)])
    db.execute(load_statement("cache_v3/delete_source_entries"), ("a",))
    db.execute(load_statement("cache_v3/delete_source_frontier"), ("a",))
    db.execute(load_statement("cache_v4/delete_source_frontier"), (1,))
    assert db.execute("SELECT * FROM source_entries").fetchall() == [("b",)]
    assert db.execute("SELECT * FROM source_frontiers").fetchall() == [("b",)]
    assert db.execute("SELECT * FROM cache_v4_source_frontiers").fetchall() == [(2,)]


def test_unfaceted_source_lookup() -> None:
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE cache_v4_sources (source_id INTEGER, source_url TEXT, source_kind TEXT, facet TEXT)")
    db.executemany(
        "INSERT INTO cache_v4_sources VALUES (?, ?, ?, ?)", [(1, "a", "channel", ""), (2, "a", "channel", "shorts")]
    )
    assert db.execute(load_statement("cache_v4/source_by_url_unfaceted"), ("a",)).fetchall() == [
        (1, "a", "channel", "")
    ]
