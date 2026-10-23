"""Manual SQLite maintenance and compatibility regression tests."""

from dataclasses import replace
from pathlib import Path
import shutil
import sqlite3

import pytest

from yt_media_tools.cache_compaction import compact_cache
from yt_media_tools.database_maintenance import (
    checkpoint_wal,
    default_policy,
    manual_full_vacuum,
    optimise_statistics,
)


def _db(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE payload(value TEXT)")
    connection.executemany("INSERT INTO payload VALUES (?)", [("x" * 2000,)] * 100)
    connection.commit()
    connection.execute("DELETE FROM payload")
    connection.commit()
    return connection


def test_legacy_compaction_uses_shared_executor(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite3"
    connection = _db(path)
    assert compact_cache is manual_full_vacuum
    result = compact_cache(connection, path)
    assert result.vacuum_performed
    assert result.after.free_pages < result.before.free_pages
    connection.close()


def test_manual_vacuum_rejects_insufficient_space(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "data.sqlite3"
    connection = _db(path)
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: type("Usage", (), {"free": 0})())
    with pytest.raises(RuntimeError, match="insufficient free disk space"):
        manual_full_vacuum(connection, path)
    assert connection.execute("SELECT count(*) FROM payload").fetchone()[0] == 0
    connection.close()


def test_statistics_and_checkpoint_preserve_data(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite3"
    connection = _db(path)
    assert checkpoint_wal(connection) is None
    optimise_statistics(connection)
    assert connection.execute("SELECT count(*) FROM payload").fetchone()[0] == 0
    connection.close()


def test_full_vacuum_never_runs_automatically() -> None:
    assert not default_policy().automatic_full
    assert not replace(default_policy(), enabled=True).automatic_full


@pytest.mark.parametrize("multiplier", [0, -1, float("nan"), float("inf")])
def test_full_vacuum_rejects_invalid_space_multiplier(tmp_path: Path, multiplier: float) -> None:
    path = tmp_path / "data.sqlite3"
    with _db(path) as connection, pytest.raises(ValueError, match="space multiplier"):
        manual_full_vacuum(connection, path, minimum_free_space_multiplier=multiplier)


def test_manual_vacuum_rejects_active_transaction(tmp_path: Path) -> None:
    path = tmp_path / "data.sqlite3"
    with _db(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(RuntimeError, match="active SQLite transaction"):
            manual_full_vacuum(connection, path)
        connection.rollback()
