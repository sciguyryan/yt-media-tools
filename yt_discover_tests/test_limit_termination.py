"""LIMIT-aware acquisition planning and early-termination behaviour."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yt_media_tools.planner import plan_limit_termination
from yt_media_tools.query import parse_query

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def fake_limit_env(tmp_path: Path, count: int = 30) -> tuple[dict[str, str], Path]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "detail.log"
    fake = fake_bin / "yt-dlp"
    fake.write_text(
        f"""#!/usr/bin/env python3
import json, os, sys
if '--version' in sys.argv:
    print('2026.08.30')
    raise SystemExit(0)
if '--flat-playlist' in sys.argv:
    for i in range({count}):
        vid = f'v{{i:03d}}'
        print(json.dumps({{'id': vid, 'title': vid}}), flush=True)
else:
    for arg in sys.argv:
        if 'watch?v=' in arg:
            vid = arg.rsplit('=', 1)[-1]
            with open(os.environ['YT_DISCOVER_DETAIL_LOG'], 'a', encoding='utf-8') as fh:
                fh.write(vid + '\\n')
            print(json.dumps({{'id': vid, 'title': vid, 'upload_date': '20260901', 'duration': 60}}), flush=True)
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["YT_DISCOVER_DETAIL_LOG"] = str(log)
    return env, log


def test_limit_planner_allows_source_order_only() -> None:
    eligible = plan_limit_termination(parse_query("SELECT id FROM @example WHERE duration < 1h LIMIT 2"))
    assert eligible.eligible
    ordered = plan_limit_termination(
        parse_query("SELECT id FROM @example WHERE duration < 1h ORDER BY upload_date DESC LIMIT 2")
    )
    assert not ordered.eligible
    assert "ORDER BY" in ordered.reason


def test_limit_planner_rejects_dynamic_fields() -> None:
    plan = plan_limit_termination(parse_query("SELECT id FROM @example WHERE raw.extra.score > 1 LIMIT 2"))
    assert not plan.eligible
    assert "dynamic fields" in plan.reason


def test_cli_limit_stops_detailed_acquisition_in_source_order(tmp_path: Path) -> None:
    env, log = fake_limit_env(tmp_path)
    result = run_cli(
        "--cache",
        str(tmp_path / "cache.sqlite3"),
        "--backend",
        "ytdlp",
        "--tab",
        "videos",
        "-v",
        "SELECT id FROM @example WHERE duration < 1h LIMIT 2",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["v000", "v001"]
    detailed = log.read_text(encoding="utf-8").splitlines()
    assert len(detailed) == 25
    assert "LIMIT-aware detailed acquisition stopped after 25 candidate(s)" in result.stderr


def test_cli_ordered_limit_remains_exhaustive(tmp_path: Path) -> None:
    env, log = fake_limit_env(tmp_path)
    result = run_cli(
        "--cache",
        str(tmp_path / "cache.sqlite3"),
        "--backend",
        "ytdlp",
        "--tab",
        "videos",
        "-v",
        "SELECT id FROM @example WHERE duration < 1h ORDER BY upload_date DESC LIMIT 2",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert len(log.read_text(encoding="utf-8").splitlines()) == 30
    assert "LIMIT-aware detailed acquisition stopped" not in result.stderr


def test_json_explain_reports_limit_eligibility() -> None:
    result = run_cli(
        "--explain-format",
        "json",
        "--explain",
        "SELECT id FROM @example WHERE duration < 1h LIMIT 2",
    )
    assert result.returncode == 0, result.stderr
    import json

    payload = json.loads(result.stdout)
    assert payload["limit_aware_termination"]["implemented"] is True
    assert payload["limit_aware_termination"]["eligible"] is True
