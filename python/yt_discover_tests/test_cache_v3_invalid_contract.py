"""Boundary tests for structurally valid and invalid historical cache-v3 databases."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from yt_discover_tests.cache_v3_contract import validate_v3_database


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _copy_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "cache-v3.sqlite3"
    shutil.copyfile(FIXTURE, path)
    return path


def _mutate(path: Path, sql: str, params: tuple[object, ...] = ()) -> None:
    db = sqlite3.connect(path)
    try:
        with db:
            db.execute(sql, params)
    finally:
        db.close()


def _codes(path: Path) -> set[str]:
    return {item.code for item in validate_v3_database(path)}


def test_canonical_fixture_satisfies_v3_structural_contract() -> None:
    assert validate_v3_database(FIXTURE) == ()


def test_wrong_schema_version_is_invalid(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(path, "UPDATE cache_meta SET value='4' WHERE key='schema_version'")
    assert "schema-version" in _codes(path)


def test_missing_required_index_is_invalid(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(path, "DROP INDEX source_entries_order")
    assert "schema-index" in _codes(path)


def test_missing_v3_column_is_invalid(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(path, "ALTER TABLE source_frontiers DROP COLUMN overlap_confirmations")
    assert "schema-shape" in _codes(path)


@pytest.mark.parametrize("raw_json", ["{broken", "[]", "null"])
def test_raw_metadata_must_be_a_json_object(tmp_path: Path, raw_json: str) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(
        path,
        "UPDATE metadata_records SET raw_json=? WHERE source_url=? AND video_id=?",
        (raw_json, "https://example.invalid/partial", "partial-1"),
    )
    assert "metadata-json-object" in _codes(path)


def test_metadata_timestamp_must_be_parseable(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(path, "UPDATE metadata_records SET fetched_at='not-a-time' WHERE video_id='partial-1'")
    assert "metadata-timestamp" in _codes(path)


def test_source_state_timestamps_must_be_parseable(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(
        path, "UPDATE source_coverage SET observed_at='not-a-time' WHERE source_url='https://example.invalid/partial'"
    )
    assert "source-coverage-timestamp" in _codes(path)


def test_source_entry_indexes_must_describe_one_contiguous_order(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(
        path,
        "UPDATE source_entries SET source_index=9 WHERE source_url=? AND video_id=?",
        ("https://www.youtube.com/@fixture/videos", "unicode-雪"),
    )
    assert "source-entry-order" in _codes(path)


def test_frontier_requires_the_ordering_it_summarises(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(path, "DELETE FROM source_entries WHERE source_url='https://www.youtube.com/@fixture/shorts'")
    assert "frontier-order" in _codes(path)


def test_frontier_head_and_count_must_match_stored_order(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(
        path,
        "UPDATE source_frontiers SET known_entries=99, head_video_id='other' WHERE source_url='https://www.youtube.com/@fixture/videos'",
    )
    assert "frontier-order" in _codes(path)


def test_json_id_disagreement_is_not_invented_as_a_v3_violation(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    db = sqlite3.connect(path)
    try:
        raw = db.execute(
            "SELECT raw_json FROM metadata_records WHERE source_url=? AND video_id=?",
            ("https://example.invalid/partial", "partial-1"),
        ).fetchone()[0]
        record = json.loads(raw)
        record["id"] = "different-id"
        with db:
            db.execute(
                "UPDATE metadata_records SET raw_json=? WHERE source_url=? AND video_id=?",
                (json.dumps(record), "https://example.invalid/partial", "partial-1"),
            )
    finally:
        db.close()
    assert validate_v3_database(path) == ()


def test_negative_counters_are_not_retroactively_forbidden(tmp_path: Path) -> None:
    path = _copy_fixture(tmp_path)
    _mutate(
        path,
        "UPDATE source_observations SET observed_entries=-7 WHERE source_url='https://example.invalid/enumeration-only'",
    )
    _mutate(path, "UPDATE source_coverage SET cached_entries=-3 WHERE source_url='https://example.invalid/partial'")
    _mutate(
        path,
        "UPDATE source_frontiers SET overlap_confirmations=-2 WHERE source_url='https://www.youtube.com/@fixture/shorts'",
    )
    assert validate_v3_database(path) == ()
