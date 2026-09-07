from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from yt_media_tools.cache import MetadataCache, SCHEMA_VERSION
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


def test_v2_cache_migrates_and_seeds_only_cardinality_matched_frontier(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO cache_meta VALUES ('schema_version', '2')")
    db.execute(
        "CREATE TABLE source_observations (source_url TEXT PRIMARY KEY, source_kind TEXT NOT NULL, last_observed_at TEXT NOT NULL, observed_entries INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE source_entries (source_url TEXT NOT NULL, video_id TEXT NOT NULL, source_index INTEGER NOT NULL, observed_at TEXT NOT NULL, PRIMARY KEY (source_url, video_id))"
    )
    when = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO source_observations VALUES (?, 'channel', ?, 2)", (SOURCE, when))
    db.execute("INSERT INTO source_entries VALUES (?, 'newer', 1, ?)", (SOURCE, when))
    db.execute("INSERT INTO source_entries VALUES (?, 'older', 2, ?)", (SOURCE, when))
    db.commit()
    db.close()
    with MetadataCache(path) as cache:
        frontier = cache.source_frontier(SOURCE)
        assert frontier is not None
        assert frontier.known_entries == 2
        assert frontier.head_video_id == "newer"
    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT value FROM cache_meta WHERE key='schema_version'").fetchone()[0] == str(
            SCHEMA_VERSION
        )
    finally:
        db.close()


def test_frontier_round_trip_preserves_source_order(tmp_path: Path) -> None:
    path = tmp_path / "cache.sqlite3"
    with MetadataCache(path) as cache:
        cache.record_source_entries(SOURCE, ["v3", "v2", "v1"])
        cache.record_source_frontier(SOURCE, "channel", ["v3", "v2", "v1"], overlap_confirmations=5)
        assert cache.source_entry_ids(SOURCE) == ["v3", "v2", "v1"]
        frontier = cache.source_frontier(SOURCE)
        assert frontier is not None
        assert frontier.known_entries == 3
        assert frontier.overlap_confirmations == 5


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


def fake_frontier_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "yt-dlp"
    fake.write_text(
        """#!/usr/bin/env python3
import json, sys
if '--version' in sys.argv:
    print('2026.08.30')
    raise SystemExit(0)
flat = '--flat-playlist' in sys.argv
if flat:
    for vid in ['new3','old5','old4','old3','old2','old1']:
        print(json.dumps({'id': vid, 'title': vid}), flush=True)
else:
    for arg in sys.argv:
        if 'watch?v=' in arg:
            vid = arg.rsplit('=', 1)[-1]
            print(json.dumps({'id': vid, 'title': vid, 'upload_date': '20260901', 'duration': 60}), flush=True)
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def test_cli_incremental_frontier_stops_after_known_overlap(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    known = ["old5", "old4", "old3", "old2", "old1", "older"]
    with MetadataCache(cache_path) as cache:
        cache.put_many(SOURCE, [{"id": vid, "title": vid, "upload_date": "20260801", "duration": 60} for vid in known])
        cache.record_source_entries(SOURCE, known)
        cache.record_source_frontier(SOURCE, "channel", known, overlap_confirmations=0)
        cache.record_source_observation(SOURCE, "channel", len(known))
    env = fake_frontier_env(tmp_path)
    result = run_cli(
        "--cache",
        str(cache_path),
        "--tab",
        "videos",
        "--backend",
        "ytdlp",
        "-v",
        "SELECT id FROM @example WHERE duration < 1h",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Incremental frontier confirmed after 6 observed entries" in result.stderr
    assert "1 new source entry" in result.stderr
    assert result.stdout.splitlines()[0] == "new3"
    with MetadataCache(cache_path) as cache:
        ids = cache.source_entry_ids(SOURCE)
        assert ids[:6] == ["new3", "old5", "old4", "old3", "old2", "old1"]
        assert "older" in ids


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


def fake_no_overlap_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin-no-overlap"
    fake_bin.mkdir()
    fake = fake_bin / "yt-dlp"
    fake.write_text(
        """#!/usr/bin/env python3
import json, sys
if '--version' in sys.argv:
    print('2026.08.30')
    raise SystemExit(0)
if '--flat-playlist' in sys.argv:
    for vid in ['fresh3','fresh2','fresh1']:
        print(json.dumps({'id': vid, 'title': vid}), flush=True)
else:
    for arg in sys.argv:
        if 'watch?v=' in arg:
            vid = arg.rsplit('=', 1)[-1]
            print(json.dumps({'id': vid, 'title': vid, 'upload_date': '20260901', 'duration': 60}), flush=True)
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def test_frontier_no_overlap_falls_back_to_complete_rebuild(tmp_path: Path) -> None:
    cache_path = tmp_path / "cache.sqlite3"
    with MetadataCache(cache_path) as cache:
        old = ["old3", "old2", "old1"]
        cache.put_many(SOURCE, [{"id": vid, "title": vid, "upload_date": "20260801", "duration": 60} for vid in old])
        cache.record_source_entries(SOURCE, old)
        cache.record_source_frontier(SOURCE, "channel", old, overlap_confirmations=0)
    result = run_cli(
        "--cache",
        str(cache_path),
        "--tab",
        "videos",
        "--backend",
        "ytdlp",
        "-v",
        "SELECT id FROM @example WHERE duration < 1h",
        env=fake_no_overlap_env(tmp_path),
    )
    assert result.returncode == 0, result.stderr
    assert "Stored frontier overlap was not confirmed before source end" in result.stderr
    with MetadataCache(cache_path) as cache:
        assert cache.source_entry_ids(SOURCE) == ["fresh3", "fresh2", "fresh1"]
        frontier = cache.source_frontier(SOURCE)
        assert frontier is not None
        assert frontier.head_video_id == "fresh3"
