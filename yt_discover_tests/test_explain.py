"""Human-readable and machine-readable EXPLAIN reporting."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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


def populate_cache(path: Path, *, complete: bool = True) -> None:
    """Create a small current cache used by offline EXPLAIN ANALYZE tests."""
    when = datetime.now(timezone.utc)
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
        cache.record_source_coverage(SOURCE, "channel", 2, complete=complete, reason="test coverage", observed_at=when)


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
    assert payload["version"] == "0.25.3"
    assert payload["acquisition"]["strategy"] == "bounded-date"
    assert payload["limit_aware_termination"]["applicable"] is True
    assert payload["limit_aware_termination"]["implemented"] is True
    assert payload["limit_aware_termination"]["eligible"] is True


def test_json_explain_reports_predicate_optimizer_rewrites() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain",
        "SELECT id FROM @example WHERE view_count >= 10 AND view_count >= 20",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    optimiser = payload["predicate_optimiser"]
    assert optimiser["status"] == "active"
    assert optimiser["changed"] is True
    assert optimiser["rewrites"] == [
        {
            "rule": "subsumed-and-predicate",
            "before": "(view_count >= 10 AND view_count >= 20)",
            "after": "view_count >= 20",
        }
    ]
    assert optimiser["optimised_query"] == "SELECT id FROM @example WHERE view_count >= 20"


def test_text_explain_reports_predicate_optimizer_rewrites() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain",
        "SELECT id FROM @example WHERE view_count >= 10 AND view_count >= 20",
    )
    assert result.returncode == 0, result.stderr
    assert "Predicate optimiser" in result.stdout
    assert "[subsumed-and-predicate]" in result.stdout
    assert "Optimised filter: view_count >= 20" in result.stdout


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


def test_json_explain_includes_row_shaping() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--explain-format",
            "json",
            "--explain",
            "SELECT DISTINCT id FROM @x LIMIT 2 OFFSET 1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["row_shaping"] == {"distinct": True, "limit": 2, "offset": 1}


def test_json_explain_reports_case_predicate_optimizer_rewrites() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain",
        "SELECT CASE WHEN duration > 1m AND duration > 2m THEN 1 ELSE 0 END AS bucket FROM @example",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    optimiser = payload["predicate_optimiser"]
    assert optimiser["changed"] is True
    assert optimiser["rewrites"] == [
        {
            "rule": "case-when-subsumed-and-predicate",
            "before": "(duration > 1m AND duration > 2m)",
            "after": "duration > 2m",
        }
    ]
    assert optimiser["optimised_query"] == "SELECT CASE WHEN duration > 2m THEN 1 ELSE 0 END AS bucket FROM @example"


def test_text_explain_handles_case_only_optimizer_rewrites_without_filter() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain",
        "SELECT CASE WHEN duration > 1m AND duration > 2m THEN 1 ELSE 0 END AS bucket FROM @example",
    )
    assert result.returncode == 0, result.stderr
    assert "[case-when-subsumed-and-predicate]" in result.stdout
    assert "Rewrites apply to predicates embedded in scalar expressions." in result.stdout
    assert "Optimised filter:" not in result.stdout
