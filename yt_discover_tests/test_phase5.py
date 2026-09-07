from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from yt_media_tools.dates import DateContext
from yt_media_tools.output import project_record
from yt_media_tools.planner import plan_limit_termination, required_query_fields
from yt_media_tools.query import QuerySyntaxError, apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def resolve(text: str, records: list[dict]):
    return resolve_query(parse_query(text), QuerySchema(records), DateContext(date_order="ymd"))


def test_distinct_deduplicates_selected_projection_after_ordering() -> None:
    records = [
        {"id": "a", "title": "same", "view_count": 1},
        {"id": "b", "title": "same", "view_count": 2},
        {"id": "c", "title": "other", "view_count": 3},
    ]
    query = resolve("SELECT DISTINCT title FROM @x ORDER BY view_count DESC", records)
    selected = apply_query(records, query)
    assert [record["id"] for record in selected] == ["c", "b"]


def test_offset_applies_before_limit() -> None:
    records = [{"id": str(i), "source_index": i} for i in range(1, 6)]
    query = resolve("SELECT id FROM @x ORDER BY source_index ASC LIMIT 2 OFFSET 2", records)
    assert [record["id"] for record in apply_query(records, query)] == ["3", "4"]


def test_offset_accepts_zero_and_rejects_negative_like_syntax() -> None:
    assert parse_query("SELECT id FROM @x OFFSET 0").offset == 0
    with pytest.raises(QuerySyntaxError, match="OFFSET requires"):
        parse_query("SELECT id FROM @x OFFSET -1")


def test_scalar_functions_projection_and_order_alias() -> None:
    records = [{"id": "a", "title": "Zulu"}, {"id": "b", "title": "alpha"}, {"id": "c", "title": None}]
    query = resolve("SELECT LOWER(title) AS folded FROM @x ORDER BY folded ASC", records)
    selected = apply_query(records, query)
    assert [project_record(record, query.select)["folded"] for record in selected] == ["alpha", "zulu", None]


def test_length_and_coalesce() -> None:
    records = [{"id": "a", "title": "abc"}, {"id": "b", "title": None}]
    q1 = resolve("SELECT LENGTH(title) AS n FROM @x", records)
    assert [project_record(r, q1.select)["n"] for r in records] == [3, None]
    q2 = resolve("SELECT COALESCE(title, 'untitled') AS title FROM @x", records)
    assert [project_record(r, q2.select)["title"] for r in records] == ["abc", "untitled"]


def test_scalar_function_required_fields_are_underlying_fields() -> None:
    query = parse_query("SELECT LOWER(title) AS t, LENGTH(description) AS n FROM @x")
    assert required_query_fields(query) == {"title", "description"}


def test_limit_termination_disabled_by_distinct_and_offset() -> None:
    assert not plan_limit_termination(parse_query("SELECT DISTINCT id FROM @x LIMIT 2")).eligible
    assert not plan_limit_termination(parse_query("SELECT id FROM @x LIMIT 2 OFFSET 1")).eligible


def test_parameter_binding_check_query() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--param",
            "start=2026-08-01",
            "--check-query",
            "SELECT id FROM @x WHERE upload_date >= :start",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "upload_date >= '2026-08-01'" in proc.stdout


def test_missing_parameter_is_an_error() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-query", "SELECT id FROM @x WHERE title = :name"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "missing value for query parameter" in proc.stderr


def test_parameters_do_not_expand_inside_quoted_strings() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--param",
            "name=unused",
            "--check-query",
            "SELECT id FROM @x WHERE title = ':name'",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode != 0
    assert "unused query parameter" in proc.stderr


def test_json_explain_includes_row_shaping() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--explain-format",
            "json",
            "--explain",
            "SELECT DISTINCT id FROM @x LIMIT 2 OFFSET 1",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["row_shaping"] == {"distinct": True, "limit": 2, "offset": 1}


def test_version_is_phase5() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--version"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert "0.18.1" in proc.stdout


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
    assert payload["version"] == "0.18.1"
    assert payload["query"]["parameters"] == {"needle": "Alpha"}
    assert payload["execution"]["offline"] is True
    assert payload["execution"]["emitted_rows"] == 1
