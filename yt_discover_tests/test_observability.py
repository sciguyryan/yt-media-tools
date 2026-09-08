from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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


def fake_ytdlp_env(tmp_path: Path, *, with_error: bool = False, count: int = 2) -> dict[str, str]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_ytdlp = fake_bin / "yt-dlp"
    records = [
        {
            "id": f"vid{index:08d}",
            "title": f"Video {index}",
            "upload_date": "20260401",
            "view_count": 2000 + index,
        }
        for index in range(1, count + 1)
    ]
    lines = [
        "#!/usr/bin/env python3",
        "import json, sys",
        f"records = {records!r}",
    ]
    if with_error:
        lines.extend(
            [
                "print('ERROR: [youtube] BTxUyJttwSk: Join this channel to get access to members-only content like this video, and other exclusive perks.', file=sys.stderr, flush=True)",
            ]
        )
    lines.extend(
        [
            "for record in records:",
            "    print(json.dumps(record), flush=True)",
        ]
    )
    fake_ytdlp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fake_ytdlp.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    return env


def test_explain_resolves_known_aliases_and_temporal_values() -> None:
    result = run_cli(
        "--explain",
        "SELECT id, views AS popularity FROM @example "
        "WHERE upload_date BETWEEN TODAY()-1yr AND TODAY() "
        "ORDER BY popularity DESC LIMIT 25",
    )
    assert result.returncode == 0, result.stderr
    assert "Type: channel" in result.stdout
    assert "popularity: view_count (count) [resolved from views]" in result.stdout
    assert "upload_date is between" in result.stdout
    assert "inclusive" in result.stdout
    assert "view_count descending; NULL values last" in result.stdout
    assert "Default serialisation: jsonl" in result.stdout
    assert "TODAY() =" in result.stdout
    assert "NOW() =" in result.stdout
    assert result.stderr == ""


def test_explain_marks_dynamic_fields_as_deferred() -> None:
    result = run_cli(
        "--explain",
        "SELECT id, channel_follower_total FROM @example WHERE channel_follower_total >= 10k",
    )
    assert result.returncode == 0, result.stderr
    assert "Deferred validation" in result.stdout
    assert "dynamic yt-dlp metadata fields" in result.stdout


def test_explain_requires_from_clause() -> None:
    result = run_cli("--explain", "SELECT id WHERE views >= 10k")
    assert result.returncode != 0
    assert "requires a complete query containing a physical FROM <source>" in result.stderr


def test_verbose_goes_to_stderr_and_keeps_stdout_machine_clean(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path)
    result = run_cli(
        "-v",
        "FROM @example WHERE views >= 1k ORDER BY upload_date ASC",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "vid00000001\nvid00000002\n"
    assert "Resolved source as channel" in result.stderr
    assert "Acquiring full video metadata with yt-dlp" in result.stderr
    assert "Acquired 1 available entries" in result.stderr
    assert "Acquisition complete: 2 available" in result.stderr
    assert "WHERE matched 2 of 2 entries" in result.stderr
    assert "Applied ordering: upload_date ASC" in result.stderr
    assert "Output format: lines" in result.stderr
    assert "Emitted 2 rows" in result.stderr


def test_double_verbose_reports_every_available_entry(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path, count=3)
    result = run_cli("-vv", "FROM @example", env=env)
    assert result.returncode == 0, result.stderr
    assert "Available entry 1: vid00000001" in result.stderr
    assert "Available entry 2: vid00000002" in result.stderr
    assert "Available entry 3: vid00000003" in result.stderr


def test_verbose_classifies_members_only_skip(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path, with_error=True)
    result = run_cli("-v", "FROM @example", env=env)
    assert result.returncode == 0, result.stderr
    assert "ERROR: [youtube] BTxUyJttwSk" in result.stderr
    assert "Skipped inaccessible entry: BTxUyJttwSk (members-only)." in result.stderr
    assert "Acquisition complete: 2 available, 1 inaccessible/skipped, 3 attempted/observed." in result.stderr


def test_report_defaults_to_stderr_without_contaminating_stdout(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path, with_error=True)
    result = run_cli("FROM @example WHERE views >= 1k LIMIT 1", "--report", env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "vid00000001\n"
    assert "yt-discover acquisition report" in result.stderr
    assert "Videos attempted/observed: 3" in result.stderr
    assert "Metadata available: 2" in result.stderr
    assert "Inaccessible/skipped: 1" in result.stderr
    assert "members-only: 1" in result.stderr
    assert "Matched before LIMIT: 2" in result.stderr
    assert "Emitted rows: 1" in result.stderr


def test_report_can_be_written_to_file(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path)
    report_path = tmp_path / "reports" / "acquisition.txt"
    result = run_cli("FROM @example", "--report", str(report_path), env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "vid00000001\nvid00000002\n"
    text = report_path.read_text(encoding="utf-8")
    assert "yt-discover acquisition report" in text
    assert "Metadata available: 2" in text
    assert "Records evaluated by WHERE: 2" in text
    assert "Emitted rows: 2" in text


def test_report_dash_explicitly_uses_stdout(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path, count=1)
    result = run_cli("FROM @example", "--report", "-", env=env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("vid00000001\nyt-discover acquisition report\n")


def test_help_and_examples_document_observability() -> None:
    help_result = run_cli("--help")
    examples_result = run_cli("--examples")
    assert help_result.returncode == 0
    assert examples_result.returncode == 0
    for text in (help_result.stdout, examples_result.stdout):
        assert "--explain" in text
        assert "-vv" in text
        assert "--report" in text
        assert "TODAY()-1yr" in text


def test_explain_describes_capabilities_and_optimisation_paths() -> None:
    result = run_cli(
        "--tab",
        "videos",
        "--explain",
        "SELECT id FROM @example WHERE upload_date BETWEEN 2026-04-01 AND 2026-06-30 AND duration < 1h LIMIT 10",
    )
    assert result.returncode == 0, result.stderr
    assert "Required fields" in result.stdout
    assert "upload_date: YouTube.js=approximate" in result.stdout
    assert "duration: YouTube.js=unavailable" in result.stdout
    assert "Acquisition plan" in result.stdout
    assert "Strategy: bounded-date" in result.stdout
    assert "Optimisation paths" in result.stdout
    assert "Bounded channel enumeration" in result.stdout
    assert "Upper date-bound pruning" in result.stdout
    assert "LIMIT-aware acquisition termination" in result.stdout
    assert "Detailed metadata is acquired in source-order batches" in result.stdout


def test_negative_warn_source_size_is_rejected() -> None:
    result = run_cli("--warn-source-size", "-1", "FROM @example")
    assert result.returncode != 0
    assert "non-negative integer" in result.stderr


def test_channel_video_query_reuses_fresh_metadata_cache(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path)
    cache_path = tmp_path / "cache" / "metadata.sqlite3"
    query = "FROM @example WHERE upload_date >= 2026-04-01 AND views >= 1k ORDER BY upload_date ASC"

    first = run_cli("--tab", "videos", "--backend", "ytdlp", "--cache", str(cache_path), "-v", query, env=env)
    assert first.returncode == 0, first.stderr
    assert "Cache outcome: 0 fresh hits" in first.stderr
    assert "2 misses" in first.stderr
    assert "Refreshing detailed metadata for 2 cache-miss/stale videos" in first.stderr

    second = run_cli("--tab", "videos", "--backend", "ytdlp", "--cache", str(cache_path), "-v", query, env=env)
    assert second.returncode == 0, second.stderr
    assert second.stdout == first.stdout
    assert "Cache outcome: 2 fresh hits, 0 stale, 0 misses" in second.stderr
    assert "Refreshing detailed metadata" not in second.stderr


def test_report_includes_cache_outcome(tmp_path: Path) -> None:
    env = fake_ytdlp_env(tmp_path)
    cache_path = tmp_path / "metadata.sqlite3"
    result = run_cli(
        "--tab",
        "videos",
        "--backend",
        "ytdlp",
        "--cache",
        str(cache_path),
        "FROM @example WHERE upload_date >= 2026-04-01",
        "--report",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "Cache\n  Enabled: yes" in result.stderr
    assert f"Path: {cache_path}" in result.stderr
    assert "Misses: 2" in result.stderr
    assert "Records written: 2" in result.stderr
