from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yt_media_tools.cache import MetadataCache, SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"
SOURCE = "https://www.youtube.com/@example/videos"


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def offline_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = ""
    return env


def populate_cache(path: Path, *, complete: bool, fetched_at: datetime | None = None) -> None:
    when = fetched_at or datetime.now(timezone.utc)
    with MetadataCache(path) as cache:
        cache.put_many(
            SOURCE,
            [
                {"id": "newer", "title": "Newer", "upload_date": "20260902", "view_count": 20},
                {"id": "older", "title": "Older", "upload_date": "20260901", "view_count": 10},
            ],
            fetched_at=when,
        )
        cache.record_source_entries(SOURCE, ["newer", "older"], observed_at=when)
        cache.record_source_coverage(
            SOURCE,
            "channel",
            2,
            complete=complete,
            reason="test complete coverage" if complete else "test partial coverage",
            observed_at=when,
        )


def test_v1_cache_migrates_to_current_schema(tmp_path: Path) -> None:
    path = tmp_path / "metadata.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('schema_version', '1')")
    db.commit()
    db.close()
    with MetadataCache(path):
        pass
    db = sqlite3.connect(path)
    try:
        version = db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0]
        tables = {name for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        db.close()
    assert version == str(SCHEMA_VERSION)
    assert "source_entries" in tables
    assert "source_coverage" in tables


def test_offline_query_uses_cache_without_external_tools(tmp_path: Path) -> None:
    cache = tmp_path / "cache.sqlite3"
    populate_cache(cache, complete=True)
    result = run_cli(
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        "SELECT id FROM @example ORDER BY upload_date ASC",
        env=offline_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "older\nnewer\n"
    assert "offline warning" not in result.stderr


def test_offline_partial_coverage_is_explicit(tmp_path: Path) -> None:
    cache = tmp_path / "cache.sqlite3"
    populate_cache(cache, complete=False)
    result = run_cli(
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        "FROM @example",
        env=offline_env(),
    )
    assert result.returncode == 0, result.stderr
    assert "offline warning" in result.stderr
    assert "source coverage is incomplete" in result.stderr
    assert "test partial coverage" in result.stderr


def test_offline_stale_required_fields_are_used_with_warning(tmp_path: Path) -> None:
    cache = tmp_path / "cache.sqlite3"
    populate_cache(cache, complete=True, fetched_at=datetime.now(timezone.utc) - timedelta(days=2))
    result = run_cli(
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        "SELECT id FROM @example WHERE views >= 10 ORDER BY upload_date ASC",
        env=offline_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "older\nnewer\n"
    assert "2 cached record(s) are stale" in result.stderr
    assert "stale values will be used without refresh" in result.stderr


def test_machine_readable_explain_is_valid_json() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain",
        "SELECT id FROM @example WHERE upload_date >= 2026-08-01 AND duration < 1h LIMIT 5",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "yt-discover-explain"
    assert payload["version"] == "0.18.1"
    assert payload["acquisition"]["strategy"] == "bounded-date"
    assert payload["limit_aware_termination"]["applicable"] is True
    assert payload["limit_aware_termination"]["implemented"] is True
    assert payload["limit_aware_termination"]["eligible"] is True


def test_explain_analyze_offline_reports_actual_execution_without_rows(tmp_path: Path) -> None:
    cache = tmp_path / "cache.sqlite3"
    populate_cache(cache, complete=True)
    result = run_cli(
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        "--explain-analyze",
        "SELECT id FROM @example ORDER BY upload_date ASC LIMIT 1",
        env=offline_env(),
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("EXPLAIN ANALYZE\n")
    assert "Strategy: offline-cache" in result.stdout
    assert "Offline: yes" in result.stdout
    assert "Records evaluated by WHERE: 2" in result.stdout
    assert "Matched before LIMIT: 2" in result.stdout
    assert "Rows that would be emitted: 1" in result.stdout
    assert "older\n" not in result.stdout


def test_explain_analyze_json_is_machine_readable(tmp_path: Path) -> None:
    cache = tmp_path / "cache.sqlite3"
    populate_cache(cache, complete=True)
    result = run_cli(
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain-analyze",
        "SELECT id FROM @example LIMIT 1",
        env=offline_env(),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["kind"] == "yt-discover-explain-analyze"
    assert payload["actual"]["offline"] is True
    assert payload["actual"]["cache"]["examined"] == 2
    assert payload["actual"]["emitted"] == 1
