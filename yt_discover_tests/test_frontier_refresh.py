"""Incremental source-frontier persistence, overlap and rebuild behaviour."""

from __future__ import annotations

import os
import subprocess
import sys
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
