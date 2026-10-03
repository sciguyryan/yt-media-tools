"""Integration tests for the real durable v3-to-v4 cache transition."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_support import MigrationEventStream
from yt_media_tools.cache_v3_to_v4_migration import execute_v3_to_v4


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _version_and_state(path: Path) -> tuple[str, str]:
    connection = sqlite3.connect(path)
    try:
        rows = dict(connection.execute("SELECT key, value FROM cache_meta"))
        return str(rows["schema_version"]), str(rows["migration_state"])
    finally:
        connection.close()


def test_real_v3_to_v4_transition_preserves_source_and_certifies_new_destination(tmp_path: Path) -> None:
    source = tmp_path / "metadata.sqlite3"
    destination = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    before = _sha256(source)
    events = []

    result = execute_v3_to_v4(
        MigrationContext(source, destination, 3, 4),
        MigrationEventStream((events.append,)),
    )

    assert result.succeeded
    assert _sha256(source) == before
    assert _version_and_state(destination) == ("4", "complete")
    connection = sqlite3.connect(destination)
    try:
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "metadata_records" not in tables
        assert "source_entries" not in tables
        assert "cache_v4_media_entities" in tables
        assert "cache_v4_ytdlp_metadata" in tables
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM cache_v4_raw_migration_accounting").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM cache_v4_sources").fetchone()[0] > 0
    finally:
        connection.close()
    assert any(event.stage == "target validation" and event.kind == "complete" for event in events)
    assert any(event.stage == "destination finalisation" and event.kind == "complete" for event in events)


def test_invalid_source_fails_before_destination_is_created(tmp_path: Path) -> None:
    source = tmp_path / "bad.sqlite3"
    destination = tmp_path / "metadata-v4.sqlite3"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE cache_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    connection.execute("INSERT INTO cache_meta VALUES('schema_version', '3')")
    connection.commit()
    connection.close()

    with pytest.raises(Exception, match="outside the cache-v3 migration contract"):
        execute_v3_to_v4(MigrationContext(source, destination, 3, 4), MigrationEventStream())
    assert not destination.exists()


def test_existing_destination_is_not_overwritten(tmp_path: Path) -> None:
    source = tmp_path / "metadata.sqlite3"
    destination = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    destination.write_bytes(b"keep me")

    with pytest.raises(Exception, match="destination already exists"):
        execute_v3_to_v4(MigrationContext(source, destination, 3, 4), MigrationEventStream())
    assert destination.read_bytes() == b"keep me"


def test_v3_row_identity_and_raw_id_disagreement_are_both_preserved(tmp_path: Path) -> None:
    source = tmp_path / "metadata.sqlite3"
    destination = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    connection = sqlite3.connect(source)
    try:
        raw = connection.execute(
            "SELECT raw_json FROM metadata_records WHERE source_url=? AND video_id=?",
            ("https://example.invalid/partial", "partial-1"),
        ).fetchone()[0]
        import json

        record = json.loads(raw)
        record["id"] = "raw-id-disagrees"
        with connection:
            connection.execute(
                "UPDATE metadata_records SET raw_json=? WHERE source_url=? AND video_id=?",
                (json.dumps(record), "https://example.invalid/partial", "partial-1"),
            )
    finally:
        connection.close()

    result = execute_v3_to_v4(MigrationContext(source, destination, 3, 4), MigrationEventStream())
    assert result.succeeded
    connection = sqlite3.connect(destination)
    try:
        row = connection.execute(
            """
            SELECT e.external_id, m.id
            FROM cache_v4_media_entities AS e
            JOIN cache_v4_ytdlp_metadata AS m USING(entity_id)
            WHERE e.external_id='partial-1'
            """
        ).fetchone()
        assert row == ("partial-1", "raw-id-disagrees")
    finally:
        connection.close()
