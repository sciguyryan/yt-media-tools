"""Persistent ID append output and duplicate suppression."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yt_media_tools.cache import MetadataCache
from yt_media_tools.output import append_unique_ids
from yt_media_tools.query import Query, SelectTerm


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


def test_append_unique_ids_is_deduplicating_and_atomic(tmp_path: Path) -> None:
    target = tmp_path / "ids.txt"
    target.write_text("a\nb\n", encoding="utf-8")
    query = Query(select=(SelectTerm("id", "id", kind="string"),))
    existing, duplicates, added = append_unique_ids([{"id": "b"}, {"id": "c"}, {"id": "c"}, {"id": "d"}], query, target)
    assert (existing, duplicates, added) == (2, 2, 2)
    assert target.read_text(encoding="utf-8") == "a\nb\nc\nd\n"


def test_append_rejects_non_id_projection(tmp_path: Path) -> None:
    query = Query(select=(SelectTerm("title", "title", kind="string"),))
    try:
        append_unique_ids([{"title": "x"}], query, tmp_path / "ids.txt")
    except ValueError as exc:
        assert "single ID projection" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_cli_append_adds_only_new_ids(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    target = tmp_path / "ids.txt"
    target.write_text("old4\n", encoding="utf-8")
    known = ["old5", "old4", "old3", "old2", "old1"]
    with MetadataCache(cache_path) as cache:
        cache.put_many(SOURCE, [{"id": vid, "title": vid, "upload_date": "20260901", "duration": 60} for vid in known])
        cache.record_source_entries(SOURCE, known)
        cache.record_source_frontier(SOURCE, "channel", known, overlap_confirmations=0)
    result = run_cli(
        "--offline",
        "--cache",
        str(cache_path),
        "--tab",
        "videos",
        "SELECT id FROM @example ORDER BY id ASC",
        "--append",
        str(target),
        "-v",
        env={**os.environ, "PATH": ""},
    )
    assert result.returncode == 0, result.stderr
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "old4"
    assert sorted(lines) == sorted(set(known))
    assert "Append outcome:" in result.stderr
