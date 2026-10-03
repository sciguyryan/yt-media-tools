"""Tests for startup migration execution, cut-over and retention policy."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from yt_media_tools.cache import MetadataCache
from yt_media_tools.cache_discovery import CURRENT_V4_FILENAME, discover_and_resolve
from yt_media_tools.cache_startup import (
    MIGRATION_LOG_FILENAME,
    CacheMigrationRetentionPolicy,
    execute_cache_startup,
)
from yt_media_tools.cache_startup_policy import decide_cache_startup


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _migration_decision(tmp_path: Path):
    shutil.copy2(FIXTURE, tmp_path / "metadata.sqlite3")
    _, resolution = discover_and_resolve(tmp_path)
    return decide_cache_startup(resolution, interactive=False)


def test_authorised_migration_cuts_over_removes_v3_and_keeps_log(tmp_path: Path) -> None:
    decision = _migration_decision(tmp_path)

    result = execute_cache_startup(tmp_path, decision)

    assert result.migrated
    assert result.active_path == tmp_path / CURRENT_V4_FILENAME
    assert not (tmp_path / "metadata.sqlite3").exists()
    assert (tmp_path / MIGRATION_LOG_FILENAME).is_file()
    _, resolution = discover_and_resolve(tmp_path)
    assert resolution.active_path == result.active_path
    with MetadataCache(result.active_path) as cache:
        item = cache.get("https://www.youtube.com/@fixture/videos", "unicode-雪")
        assert item is not None
        assert item.record["title"] == "雪と星"


def test_successful_cutover_can_retain_legacy_source(tmp_path: Path) -> None:
    decision = _migration_decision(tmp_path)

    result = execute_cache_startup(
        tmp_path,
        decision,
        retention=CacheMigrationRetentionPolicy(retain_source_after_cutover=True),
    )

    assert result.migrated
    assert (tmp_path / "metadata.sqlite3").is_file()
    assert (tmp_path / CURRENT_V4_FILENAME).is_file()


def test_failed_migration_removes_destination_but_keeps_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    decision = _migration_decision(tmp_path)

    def fail(context, events):
        context.destination_path.write_bytes(b"incomplete")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr("yt_media_tools.cache_startup.execute_v3_to_v4", fail)

    with pytest.raises(RuntimeError, match="injected migration failure"):
        execute_cache_startup(tmp_path, decision)

    assert (tmp_path / "metadata.sqlite3").is_file()
    assert not (tmp_path / CURRENT_V4_FILENAME).exists()
    assert (tmp_path / MIGRATION_LOG_FILENAME).is_file()


def test_failed_migration_destination_can_be_retained_for_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decision = _migration_decision(tmp_path)

    def fail(context, events):
        context.destination_path.write_bytes(b"incomplete")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr("yt_media_tools.cache_startup.execute_v3_to_v4", fail)

    with pytest.raises(RuntimeError, match="injected migration failure"):
        execute_cache_startup(
            tmp_path,
            decision,
            retention=CacheMigrationRetentionPolicy(retain_failed_destination=True),
        )

    assert (tmp_path / "metadata.sqlite3").is_file()
    assert (tmp_path / CURRENT_V4_FILENAME).read_bytes() == b"incomplete"
    assert (tmp_path / MIGRATION_LOG_FILENAME).is_file()


def test_fresh_startup_creates_complete_v4_cache(tmp_path: Path) -> None:
    _, resolution = discover_and_resolve(tmp_path)
    decision = decide_cache_startup(resolution, interactive=False)

    result = execute_cache_startup(tmp_path, decision)

    assert result.created
    assert result.active_path == tmp_path / CURRENT_V4_FILENAME
    with MetadataCache(result.active_path) as cache:
        assert cache.schema_version == 4
        assert cache.put_many("https://example.invalid/source", [{"id": "fresh", "title": "Fresh"}]) == 1
        item = cache.get("https://example.invalid/source", "fresh")
        assert item is not None
        assert item.record["title"] == "Fresh"


def test_v4_runtime_persists_source_state_without_recreating_v3_tables(tmp_path: Path) -> None:
    _, resolution = discover_and_resolve(tmp_path)
    result = execute_cache_startup(tmp_path, decide_cache_startup(resolution, interactive=False))

    with MetadataCache(result.active_path) as cache:
        cache.put_many("https://example.invalid/source", [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}])
        cache.record_source_entries("https://example.invalid/source", ["b", "a"])
        cache.record_source_observation("https://example.invalid/source", "channel", 2)
        cache.record_source_coverage(
            "https://example.invalid/source", "channel", 2, complete=True, reason="complete test view"
        )
        cache.record_source_frontier("https://example.invalid/source", "channel", ["b", "a"], overlap_confirmations=2)
        assert cache.source_entry_ids("https://example.invalid/source") == ["b", "a"]
        assert cache.source_coverage("https://example.invalid/source").complete
        assert cache.source_frontier("https://example.invalid/source").head_video_id == "b"
        tables = {str(row[0]) for row in cache._db().execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "metadata_records" not in tables
        assert "source_entries" not in tables
        assert "source_coverage" not in tables
        assert "source_frontiers" not in tables


def test_triggering_offline_query_continues_after_automatic_cutover(tmp_path: Path) -> None:
    import subprocess
    import sys

    cache_directory = tmp_path / "yt-discover"
    cache_directory.mkdir()
    source = cache_directory / "metadata.sqlite3"
    shutil.copy2(FIXTURE, source)
    environment = os.environ.copy()
    environment["XDG_CACHE_HOME"] = str(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parents[1] / "yt-discover.py"),
            "--offline",
            "--tab",
            "videos",
            "SELECT id FROM @fixture ORDER BY id ASC",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["null-fields", "shared-video", "unicode-雪"]
    assert not source.exists()
    assert (cache_directory / CURRENT_V4_FILENAME).is_file()
    assert (cache_directory / MIGRATION_LOG_FILENAME).is_file()


def test_concurrent_managed_startup_serialises_migration(tmp_path: Path) -> None:
    """Two processes may start together, but only one may migrate the managed cache."""
    import subprocess
    import sys

    cache_directory = tmp_path / "yt-discover"
    cache_directory.mkdir()
    source = cache_directory / "metadata.sqlite3"
    shutil.copy2(FIXTURE, source)
    environment = os.environ.copy()
    environment["XDG_CACHE_HOME"] = str(tmp_path)
    command = [
        sys.executable,
        str(Path(__file__).parents[1] / "yt-discover.py"),
        "--offline",
        "--tab",
        "videos",
        "SELECT id FROM @fixture ORDER BY id ASC",
    ]
    processes = [
        subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        for _ in range(2)
    ]
    results = [process.communicate(timeout=30) + (process.returncode,) for process in processes]

    for stdout, stderr, returncode in results:
        assert returncode == 0, stderr
        assert stdout.splitlines() == ["null-fields", "shared-video", "unicode-雪"]
    assert not source.exists()
    assert (cache_directory / CURRENT_V4_FILENAME).is_file()
