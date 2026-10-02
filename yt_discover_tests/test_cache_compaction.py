"""Explicit SQLite cache checkpoint and compaction tests."""

from pathlib import Path
import sqlite3

import pytest

from yt_media_tools.cache_compaction import compact_cache, measure_sqlite_storage


def _database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("CREATE TABLE payload(value TEXT NOT NULL)")
    connection.commit()
    return connection


def test_measurement_is_read_only(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    connection = _database(path)
    before = connection.total_changes
    status = measure_sqlite_storage(connection, path)
    assert status.page_size > 0
    assert status.page_count > 0
    assert status.database_bytes is not None
    assert connection.total_changes == before
    connection.close()


def test_compaction_reclaims_freelist_pages_and_keeps_wal_mode(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    connection = _database(path)
    connection.executemany("INSERT INTO payload(value) VALUES (?)", [("x" * 2000,)] * 300)
    connection.commit()
    connection.execute("DELETE FROM payload")
    connection.commit()
    before = measure_sqlite_storage(connection, path)
    assert before.free_pages > 0

    result = compact_cache(connection, path)

    assert result.journal_mode == "wal"
    assert result.auto_vacuum == "none"
    assert result.checkpoint_attempted
    assert result.checkpoint_busy == 0
    assert result.vacuum_performed
    assert result.after.free_pages == 0
    assert result.after.page_count < result.before.page_count
    assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    connection.close()


def test_compaction_skips_vacuum_without_free_pages(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    connection = _database(path)
    result = compact_cache(connection, path)
    assert result.checkpoint_attempted
    assert not result.vacuum_performed
    connection.close()


def test_compaction_rejects_active_transaction(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    connection = _database(path)
    connection.execute("INSERT INTO payload(value) VALUES ('pending')")
    assert connection.in_transaction
    with pytest.raises(RuntimeError, match="active SQLite transaction"):
        compact_cache(connection, path)
    connection.rollback()
    connection.close()


def test_compaction_does_not_checkpoint_delete_journal_database(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE payload(value TEXT NOT NULL)")
    connection.commit()
    result = compact_cache(connection, path)
    assert result.journal_mode == "delete"
    assert not result.checkpoint_attempted
    connection.close()
