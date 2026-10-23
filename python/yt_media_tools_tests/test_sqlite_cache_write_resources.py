"""Compatibility checks for fixed cache-v4 write statement resources."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_collection_upsert_preserves_entity_and_field_positions():
    db = sqlite3.connect(":memory:")
    db.execute(
        "CREATE TABLE cache_v4_ytdlp_collections (entity_id INTEGER PRIMARY KEY, tags_json TEXT, categories_json TEXT, formats_json TEXT, chapters_json TEXT, thumbnails_json TEXT)"
    )
    statement = load_statement("cache_v4/upsert_ytdlp_collections")
    db.execute(statement, (1, "tags", "categories", "formats", "chapters", "thumbnails"))
    db.execute(statement, (1, "new", None, "f", "c", "t"))
    assert db.execute("SELECT * FROM cache_v4_ytdlp_collections").fetchall() == [(1, "new", None, "f", "c", "t")]


def test_historical_acquisition_update_is_scoped_to_detailed_ytdlp():
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE cache_v4_providers (provider_id INTEGER PRIMARY KEY, provider_key TEXT);
        CREATE TABLE cache_v4_acquisition_groups (acquisition_group_id INTEGER PRIMARY KEY, provider_id INTEGER, group_key TEXT);
        CREATE TABLE cache_v4_acquisition_state (entity_id INTEGER, provider_id INTEGER, acquisition_group_id INTEGER, last_attempt_at TEXT, last_success_at TEXT);
        INSERT INTO cache_v4_providers VALUES (1, 'yt-dlp'), (2, 'other');
        INSERT INTO cache_v4_acquisition_groups VALUES (10, 1, 'detailed'), (11, 1, 'basic'), (20, 2, 'detailed');
        INSERT INTO cache_v4_acquisition_state VALUES (3, 1, 10, NULL, NULL), (3, 1, 11, NULL, NULL), (3, 2, 20, NULL, NULL);
    """)
    db.execute(load_statement("cache_v4/update_historical_detailed_acquisition"), ("time", "time", 3))
    assert db.execute(
        "SELECT acquisition_group_id, last_success_at FROM cache_v4_acquisition_state ORDER BY acquisition_group_id"
    ).fetchall() == [(10, "time"), (11, None), (20, None)]


def test_existing_migration_state_resource_is_reused():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('migration_state', 'complete')")
    assert db.execute(load_statement("common/cache_migration_state")).fetchone() == ("complete",)
