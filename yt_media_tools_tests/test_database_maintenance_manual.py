"""Manual SQLite maintenance and compatibility regression tests."""

from dataclasses import replace
from pathlib import Path
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
    from yt_media_tools import database_maintenance

    monkeypatch.setattr(
        database_maintenance.shutil if hasattr(database_maintenance, "shutil") else __import__("shutil"),
        "disk_usage",
        lambda _path: type("Usage", (), {"free": 0})(),
    )
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
