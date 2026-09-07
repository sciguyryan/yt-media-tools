"""Offline query execution against persistent metadata-cache state."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yt_media_tools.cache import MetadataCache


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
