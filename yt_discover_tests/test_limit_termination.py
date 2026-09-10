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
import json, os, sys, time
if '--version' in sys.argv:
    print('2026.08.30')
    raise SystemExit(0)
if '--flat-playlist' in sys.argv:
    for i in range({count}):
        vid = f'v{{i:03d}}'
        with open(os.environ['YT_DISCOVER_ENUM_LOG'], 'a', encoding='utf-8') as fh:
            fh.write(vid + '\\n')
        print(json.dumps({{'id': vid, 'title': vid}}), flush=True)
        time.sleep(0.01)
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
    env["YT_DISCOVER_ENUM_LOG"] = str(tmp_path / "enum.log")
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


def test_cli_limit_with_offset_stops_after_offset_plus_limit_matches(tmp_path: Path) -> None:
    env, log = fake_limit_env(tmp_path, count=80)
    result = run_cli(
        "--cache",
        str(tmp_path / "cache.sqlite3"),
        "--backend",
        "ytdlp",
        "--tab",
        "videos",
        "-v",
        "SELECT id FROM @example WHERE duration < 1h LIMIT 2 OFFSET 30",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["v030", "v031"]
    detailed = log.read_text(encoding="utf-8").splitlines()
    assert len(detailed) == 50
    assert "32 authoritative match(es) were sufficient for OFFSET + LIMIT" in result.stderr


def test_limit_planner_stops_lightweight_enumeration_when_complete_query_is_enumeration_authoritative() -> None:
    from yt_media_tools.sources import resolve_source_request
    from yt_media_tools.staged_predicates import plan_predicate_stages

    query = parse_query("SELECT id FROM @example WHERE title LIKE 'v%' LIMIT 2 OFFSET 3")
    source = resolve_source_request("@example", facet="videos")
    plan = plan_limit_termination(query, source=source, predicate_stages=plan_predicate_stages(query, source=source))
    assert plan.eligible
    assert plan.mode == "enumeration-match"
    assert plan.required_matches == 5
    assert plan.stops_enumeration


def test_limit_planner_keeps_detailed_predicates_on_detailed_termination_path() -> None:
    from yt_media_tools.sources import resolve_source_request
    from yt_media_tools.staged_predicates import plan_predicate_stages

    query = parse_query("SELECT id FROM @example WHERE duration < 1h LIMIT 2")
    source = resolve_source_request("@example", facet="videos")
    plan = plan_limit_termination(query, source=source, predicate_stages=plan_predicate_stages(query, source=source))
    assert plan.mode == "detailed-match"
    assert plan.stops_detailed_acquisition


def test_limit_planner_rejects_volatile_queries() -> None:
    plan = plan_limit_termination(parse_query("SELECT RANDOM() AS r FROM @example LIMIT 2"))
    assert not plan.eligible
    assert "volatile" in plan.reason


def test_limit_planner_keeps_cte_and_union_as_proof_barriers() -> None:
    assert not plan_limit_termination(
        parse_query("WITH c AS (SELECT id FROM @example) SELECT id FROM c LIMIT 2")
    ).eligible
    assert not plan_limit_termination(parse_query("SELECT id FROM @a UNION ALL SELECT id FROM @b LIMIT 2")).eligible


def test_cli_enumeration_only_limit_stops_source_enumeration(tmp_path: Path) -> None:
    env, detail_log = fake_limit_env(tmp_path, count=80)
    result = run_cli(
        "--cache",
        str(tmp_path / "cache.sqlite3"),
        "--backend",
        "ytdlp",
        "--tab",
        "videos",
        "-v",
        "SELECT id FROM @example LIMIT 2 OFFSET 3",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["v003", "v004"]
    assert not detail_log.exists()
    enumerated = (tmp_path / "enum.log").read_text(encoding="utf-8").splitlines()
    assert 5 <= len(enumerated) < 80
    assert "LIMIT-aware source enumeration stopped" in result.stderr
    assert "5 authoritative match(es) were sufficient for OFFSET + LIMIT" in result.stderr


def test_cli_enumeration_predicate_stops_after_enough_matching_rows(tmp_path: Path) -> None:
    env, detail_log = fake_limit_env(tmp_path, count=80)
    result = run_cli(
        "--cache",
        str(tmp_path / "cache.sqlite3"),
        "--backend",
        "ytdlp",
        "--tab",
        "videos",
        "-v",
        "SELECT id FROM @example WHERE title LIKE 'v0%' LIMIT 2 OFFSET 3",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["v003", "v004"]
    assert not detail_log.exists()
    enumerated = (tmp_path / "enum.log").read_text(encoding="utf-8").splitlines()
    assert 5 <= len(enumerated) < 80
    assert "LIMIT-aware source enumeration stopped" in result.stderr


def test_json_explain_distinguishes_enumeration_and_detailed_limit_modes() -> None:
    import json

    enumeration = run_cli(
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain",
        "SELECT id FROM @example WHERE title LIKE 'v%' LIMIT 2 OFFSET 3",
    )
    assert enumeration.returncode == 0, enumeration.stderr
    payload = json.loads(enumeration.stdout)
    assert payload["limit_aware_termination"]["mode"] == "enumeration-match"
    assert payload["limit_aware_termination"]["required_matches"] == 5
    assert payload["limit_aware_termination"]["stops_source_enumeration"] is True
    assert payload["limit_aware_termination"]["backend_range_lowered"] is False

    detailed = run_cli(
        "--tab",
        "videos",
        "--explain-format",
        "json",
        "--explain",
        "SELECT id FROM @example WHERE duration < 1h LIMIT 2",
    )
    assert detailed.returncode == 0, detailed.stderr
    payload = json.loads(detailed.stdout)
    assert payload["limit_aware_termination"]["mode"] == "detailed-match"
    assert payload["limit_aware_termination"]["stops_source_enumeration"] is False
    assert payload["limit_aware_termination"]["stops_detailed_acquisition"] is True
