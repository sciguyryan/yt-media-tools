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
    assert payload["version"] == "0.27.4"
    assert payload["query"]["parameters"] == {"needle": "Alpha"}
    assert payload["execution"]["offline"] is True
    assert payload["execution"]["emitted_rows"] == 1


def test_composed_provenance_records_per_source_acquisition_counts(tmp_path: Path) -> None:
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ytdlp = fake_bin / "yt-dlp"
    fake_ytdlp.write_text(
        "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'id': 'one', 'title': 'One'}))\n",
        encoding="utf-8",
    )
    fake_ytdlp.chmod(0o755)

    provenance = tmp_path / "composed-provenance.json"
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            str(provenance),
            "SELECT id FROM @example UNION ALL SELECT id FROM 'https://www.twitch.tv/example/videos'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["source"]["type"] == "union"
    assert len(payload["sources"]) == 2
    assert [source["acquired_records"] for source in payload["sources"]] == [1, 1]
    assert payload["execution"]["normalised_records"] == 2
    assert payload["execution"]["emitted_rows"] == 2


def test_of_provenance_records_logical_facet_and_adapter(tmp_path: Path) -> None:
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ytdlp = fake_bin / "yt-dlp"
    fake_ytdlp.write_text(
        "#!/usr/bin/env python3\nimport json\nprint(json.dumps({'id': 'one', 'title': 'One'}))\n",
        encoding="utf-8",
    )
    fake_ytdlp.chmod(0o755)

    provenance = tmp_path / "facet-provenance.json"
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            str(provenance),
            "SELECT id FROM @example OF shorts",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["source"]["facet"] == "shorts"
    assert payload["source"]["adapter"] == "youtube-channel"
    assert payload["source"]["tab"] is None
    assert payload["sources"][0]["facet"] == "shorts"
    assert payload["sources"][0]["adapter"] == "youtube-channel"


def test_same_source_cross_facet_provenance_keeps_requests_independent(tmp_path: Path) -> None:
    import os

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ytdlp = fake_bin / "yt-dlp"
    fake_ytdlp.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "url = sys.argv[-1]\n"
        "facet = 'shorts' if url.endswith('/shorts') else 'videos'\n"
        "print(json.dumps({'id': 'shared', 'title': facet}))\n",
        encoding="utf-8",
    )
    fake_ytdlp.chmod(0o755)

    provenance = tmp_path / "cross-facet-provenance.json"
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            str(provenance),
            (
                "SELECT id, title FROM @example OF videos UNION ALL "
                "SELECT id, title FROM @example OF shorts ORDER BY title"
            ),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert [json.loads(line) for line in proc.stdout.splitlines()] == [
        {"id": "shared", "title": "shorts"},
        {"id": "shared", "title": "videos"},
    ]
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert [source["facet"] for source in payload["sources"]] == ["videos", "shorts"]
    assert [source["acquired_records"] for source in payload["sources"]] == [1, 1]
    assert payload["execution"]["normalised_records"] == 2
    assert payload["execution"]["emitted_rows"] == 2
