from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from yt_media_tools.dates import DateContext
from yt_media_tools.youtubejs import _published_date


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


def fake_tool_env(tmp_path: Path, *, youtubejs_ok: bool = True, youtubejs_runtime_fail: bool = False) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    fake_ytdlp = fake_bin / "yt-dlp"
    fake_ytdlp.write_text(
        """#!/usr/bin/env python3
import json, sys
if '--version' in sys.argv:
    print('2099.01.01')
    raise SystemExit(0)
if '--flat-playlist' in sys.argv:
    for index, stamp in enumerate(['20260901', '20260601', '20260415', '20260101', '20251201', '20251101'], 1):
        print(json.dumps({'id': f'flat{index:08d}', 'upload_date': stamp}), flush=True)
    raise SystemExit(0)
for index in range(1, 7):
    print(json.dumps({'id': f'flat{index:08d}', 'title': f'Video {index}', 'upload_date': '20260415', 'view_count': 1000 + index}), flush=True)
""",
        encoding="utf-8",
    )
    fake_ytdlp.chmod(0o755)

    fake_node = fake_bin / "node"
    fake_node.write_text(
        f"""#!/usr/bin/env python3
import json, sys
if '--version' in sys.argv:
    print('v24.0.0')
    raise SystemExit(0)
mode = sys.argv[2] if len(sys.argv) > 2 else ''
if mode == '--check':
    if {youtubejs_ok!r}:
        print(json.dumps({{'available': True, 'version': '18.0.0'}}))
        raise SystemExit(0)
    print("[yt-discover:youtubejs] Error [ERR_MODULE_NOT_FOUND]: Cannot find package 'youtubei.js'", file=sys.stderr)
    raise SystemExit(1)
if mode == '--enumerate-channel-videos':
    if {youtubejs_runtime_fail!r}:
        print('[yt-discover:youtubejs] simulated runtime failure', file=sys.stderr)
        raise SystemExit(1)
    published = ['3 days ago', '2 months ago', '4 months ago', '8 months ago', '9 months ago', '10 months ago']
    for index, text in enumerate(published, 1):
        print(json.dumps({{'id': f'flat{{index:08d}}', 'title': f'Video {{index}}', 'published_text': text}}), flush=True)
    raise SystemExit(0)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    fake_node.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def test_tool_check_detects_optional_youtubejs(tmp_path: Path) -> None:
    env = fake_tool_env(tmp_path)
    result = run_cli("--check-tools", env=env)
    assert result.returncode == 0, result.stderr
    assert "yt-dlp       available  2099.01.01" in result.stdout
    assert "Node.js      available  v24.0.0" in result.stdout
    assert "YouTube.js   available  18.0.0" in result.stdout
    assert "YouTube.js: resolved from /opt/node_modules/youtubei.js/dist/src/platform/node.js" in result.stdout
    assert "youtubejs  channel continuation enumeration" in result.stdout


def test_auto_announces_missing_youtubejs_and_uses_ytdlp_bounded_fallback(tmp_path: Path) -> None:
    env = fake_tool_env(tmp_path, youtubejs_ok=False)
    result = run_cli(
        "--tab",
        "videos",
        "FROM @example WHERE upload_date >= 2026-04-01",
        "--backend",
        "auto",
        "--report",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "optional YouTube.js backend unavailable; using yt-dlp bounded enumeration" in result.stderr
    assert "Selected backend: ytdlp" in result.stderr
    assert "Fallback used: yes" in result.stderr


def test_auto_prefers_youtubejs_for_bounded_enumeration(tmp_path: Path) -> None:
    env = fake_tool_env(tmp_path)
    result = run_cli(
        "--tab",
        "videos",
        "FROM @example WHERE upload_date >= 2026-04-01",
        "--backend",
        "auto",
        "-v",
        "--report",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Enumeration backend: youtubejs (requested: auto)." in result.stderr
    assert "Selected backend: youtubejs" in result.stderr
    assert "Fallback used: no" in result.stderr


def test_auto_runtime_failure_falls_back_to_ytdlp(tmp_path: Path) -> None:
    env = fake_tool_env(tmp_path, youtubejs_runtime_fail=True)
    result = run_cli(
        "--tab",
        "videos",
        "FROM @example WHERE upload_date >= 2026-04-01",
        "--backend",
        "auto",
        "--report",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "YouTube.js enumeration failed; falling back to yt-dlp bounded enumeration" in result.stderr
    assert "Selected backend: ytdlp" in result.stderr
    assert "Fallback used: yes" in result.stderr
    assert "simulated runtime failure" in result.stderr


def test_explicit_youtubejs_runtime_failure_is_fatal(tmp_path: Path) -> None:
    env = fake_tool_env(tmp_path, youtubejs_runtime_fail=True)
    result = run_cli(
        "--tab",
        "videos",
        "FROM @example WHERE upload_date >= 2026-04-01",
        "--backend",
        "youtubejs",
        env=env,
    )
    assert result.returncode != 0
    assert "YouTube.js enumeration failed" in result.stderr
    assert "falling back" not in result.stderr


def test_relative_publication_date_has_uncertainty() -> None:
    from datetime import datetime, timezone

    context = DateContext(now=datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc))
    parsed = _published_date("Premiered 2 months ago", context)
    assert parsed is not None
    value, uncertainty = parsed
    assert value.isoformat() == "2026-07-04"
    assert uncertainty.days == 35
