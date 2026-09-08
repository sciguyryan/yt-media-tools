"""Query provenance sidecar content and offline execution metadata."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def test_offline_provenance_sidecar_records_query_and_execution(tmp_path: Path) -> None:
    from datetime import datetime, timezone
    from yt_media_tools.cache import MetadataCache

    cache_path = tmp_path / "cache.sqlite3"
    source = "https://www.youtube.com/@example/videos"
    with MetadataCache(cache_path) as cache:
        cache.put_many(
            source, [{"id": "a", "title": "Alpha", "upload_date": "20260901"}], fetched_at=datetime.now(timezone.utc)
        )
        cache.record_source_entries(source, ["a"])
        cache.record_source_coverage(source, "channel", 1, complete=True, reason="test coverage")

    provenance = tmp_path / "provenance.json"
    env = dict(**__import__("os").environ)
    env["PATH"] = ""
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--offline",
            "--cache",
            str(cache_path),
            "--tab",
            "videos",
            "--provenance",
            str(provenance),
            "--param",
            "needle=Alpha",
            "SELECT id FROM @example WHERE title = :needle",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["kind"] == "yt-discover-query-provenance"
    assert payload["version"] == "0.23.3"
    assert payload["query"]["parameters"] == {"needle": "Alpha"}
    assert payload["execution"]["offline"] is True
    assert payload["execution"]["emitted_rows"] == 1
