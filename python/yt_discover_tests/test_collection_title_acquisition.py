from __future__ import annotations

import json
import os
from pathlib import Path

from yt_discover_tests.cli_harness import run_cli


PLAYLIST_ID = "PL0B8vmRvtPxz_cNoQzs6Rd1czBtBpejNJ"
SECOND_PLAYLIST_ID = "PL5dr1EHvfwpNsTb7LeUmMRczY1v7M4fzL"


def _playlist_ytdlp_env(tmp_path: Path) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ytdlp = fake_bin / "yt-dlp"
    fake_ytdlp.write_text(
        """#!/usr/bin/env python3
import json
import sys

if "--version" in sys.argv:
    print("2026.10.08")
elif "--flat-playlist" in sys.argv:
    for index in range(1, 3):
        print(json.dumps({
            "id": f"vid{index:08d}",
            "title": f"Video {index}",
            "playlist_title": "Current playlist title",
        }))
else:
    print("DETAILED_ACQUISITION", file=sys.stderr)
    for index in range(1, 3):
        print(json.dumps({
            "id": f"vid{index:08d}",
            "title": f"Video {index}",
            "availability": "public",
        }))
""",
        encoding="utf-8",
    )
    fake_ytdlp.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(fake_bin) + os.pathsep + environment.get("PATH", "")
    return environment


def test_collection_output_preserves_title_observed_before_detailed_acquisition(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"
    cache_path = tmp_path / "cache" / "metadata.sqlite3"

    result = run_cli(
        "--cache",
        str(cache_path),
        "--collection-output",
        str(collection_path),
        f"SELECT id, availability FROM {PLAYLIST_ID} ORDER BY source_index",
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "DETAILED_ACQUISITION" in result.stderr
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    assert payload["collection"]["metadata"] == {
        "id": PLAYLIST_ID,
        "title": "Current playlist title",
        "webpage_url": f"https://www.youtube.com/playlist?list={PLAYLIST_ID}",
    }


def test_collection_title_does_not_add_detailed_per_video_acquisition(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"

    result = run_cli(
        "--no-cache",
        "--collection-output",
        str(collection_path),
        f"SELECT id FROM {PLAYLIST_ID} ORDER BY source_index",
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "DETAILED_ACQUISITION" not in result.stderr
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    assert payload["collection"]["metadata"]["title"] == "Current playlist title"


def test_explicit_collection_title_overrides_automatic_title(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"

    result = run_cli(
        "--no-cache",
        "--collection-output",
        str(collection_path),
        "--collection-title",
        "Explicit title",
        f"SELECT id FROM {PLAYLIST_ID} ORDER BY source_index",
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    assert payload["collection"]["metadata"]["title"] == "Explicit title"


def test_constructed_collection_accepts_explicit_title_without_source_identity(tmp_path: Path) -> None:
    collection_path = tmp_path / "collection.json"
    query = f"SELECT id FROM {PLAYLIST_ID} UNION ALL SELECT id FROM {SECOND_PLAYLIST_ID}"

    result = run_cli(
        "--no-cache",
        "--collection-output",
        str(collection_path),
        "--collection-title",
        "Combined collection",
        query,
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(collection_path.read_text(encoding="utf-8"))
    assert payload["collection"]["metadata"] == {"title": "Combined collection"}


def test_collection_title_requires_collection_output(tmp_path: Path) -> None:
    result = run_cli(
        "--collection-title",
        "Detached title",
        f"SELECT id FROM {PLAYLIST_ID}",
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode != 0
    assert "--collection-title requires --collection-output" in result.stderr


def test_collection_title_rejects_whitespace_only_value(tmp_path: Path) -> None:
    result = run_cli(
        "--collection-output",
        str(tmp_path / "collection.json"),
        "--collection-title",
        "   ",
        f"SELECT id FROM {PLAYLIST_ID}",
        env=_playlist_ytdlp_env(tmp_path),
    )

    assert result.returncode != 0
    assert "--collection-title must contain at least one non-whitespace character" in result.stderr
