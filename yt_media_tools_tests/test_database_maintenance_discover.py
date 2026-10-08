"""Discover post-operation maintenance boundary and fresh-cache behaviour."""

import sqlite3

import pytest

from yt_media_tools import discover_application
from yt_media_tools.cache import initialise_v4_cache
from yt_media_tools.database_maintenance import MaintenanceOutcome


def test_fresh_v4_cache_uses_incremental_vacuum(tmp_path):
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA auto_vacuum").fetchone()[0] == 2


@pytest.mark.parametrize("status", [0, 1])
def test_post_operation_maintenance_preserves_exit_status(monkeypatch, tmp_path, status):
    path = tmp_path / "metadata-v4.sqlite3"
    calls = []

    def run(_argv):
        discover_application._active_maintenance_cache.set(path)
        return status

    def maintain(source, database, policy):
        calls.append((source, database))
        return MaintenanceOutcome("deferred", "busy")

    monkeypatch.setattr(discover_application, "_run_application", run)
    monkeypatch.setattr(discover_application, "incremental_maintenance", maintain)
    assert discover_application.main([]) == status
    assert calls == [(path, "metadata_cache")]


def test_no_cache_does_not_invoke_maintenance(monkeypatch):
    monkeypatch.setattr(discover_application, "_run_application", lambda _argv: 0)
    monkeypatch.setattr(
        discover_application, "incremental_maintenance", lambda *args: pytest.fail("unexpected maintenance")
    )
    assert discover_application.main([]) == 0
