"""Exercise shared cache metadata SQL against SQLite itself."""

import sqlite3

from yt_media_tools.sqlite import load_statement


def test_shared_cache_metadata_inspection_and_finalisation():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    assert connection.execute(load_statement("common/cache_meta_table_exists")).fetchone() == ("cache_meta",)
    assert connection.execute(load_statement("common/cache_schema_version")).fetchone() is None
    connection.execute("INSERT INTO cache_meta VALUES ('schema_version', '4')")
    connection.execute("INSERT INTO cache_meta VALUES ('migration_state', 'incomplete')")
    assert connection.execute(load_statement("common/cache_schema_version")).fetchone() == ("4",)
    assert connection.execute(load_statement("common/cache_migration_state")).fetchone() == ("incomplete",)
    with connection:
        connection.execute(load_statement("common/cache_set_migration_complete"))
    assert connection.execute(load_statement("common/cache_migration_state")).fetchone() == ("complete",)
    connection.close()
