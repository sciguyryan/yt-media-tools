"""Certification tests for the historical v3-to-v4 migration."""

from __future__ import annotations

from pathlib import Path
import shutil
import sqlite3

import pytest

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_support import MigrationEventStream
from yt_media_tools.cache_v3_to_v4_migration import execute_v3_to_v4
from yt_media_tools.cache_v3_to_v4_verification import (
    MigrationVerificationMode,
    certify_v3_to_v4,
)


FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _migrate(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    result = execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())
    assert result.succeeded
    return source, target


def test_full_certification_checks_every_detailed_record_and_source_state(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    certification = certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)
    connection = sqlite3.connect(source)
    try:
        detailed = int(connection.execute("SELECT COUNT(*) FROM metadata_records").fetchone()[0])
        identities = int(connection.execute("SELECT COUNT(DISTINCT video_id) FROM metadata_records").fetchone()[0])
        sources = len(
            {
                str(row[0])
                for table in ("source_observations", "source_entries", "source_coverage", "source_frontiers")
                for row in connection.execute(f"SELECT DISTINCT source_url FROM {table}")
            }
        )
    finally:
        connection.close()
    assert certification.metadata_records == detailed
    assert certification.semantic_records_checked == identities
    assert certification.source_states_checked == sources


def test_certification_rejects_registered_metadata_mismatch(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    connection = sqlite3.connect(target)
    with connection:
        connection.execute("UPDATE cache_v4_ytdlp_metadata SET title='corrupted'")
    connection.close()
    with pytest.raises(RuntimeError, match="registered metadata mismatch"):
        certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)


def test_certification_rejects_historical_timestamp_mismatch(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    connection = sqlite3.connect(target)
    with connection:
        connection.execute(
            "UPDATE cache_v4_acquisition_state SET last_attempt_at='2000-01-01T00:00:00+00:00', last_success_at='2000-01-01T00:00:00+00:00'"
        )
    connection.close()
    with pytest.raises(RuntimeError, match="acquisition provenance/timestamp mismatch"):
        certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)


def test_certification_rejects_source_coverage_mismatch(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    connection = sqlite3.connect(target)
    with connection:
        connection.execute("UPDATE cache_v4_source_coverage SET reason='corrupted'")
    connection.close()
    with pytest.raises(RuntimeError, match="source coverage mismatch"):
        certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)


def test_certification_rejects_frontier_identity_mismatch(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    connection = sqlite3.connect(target)
    other = connection.execute(
        "SELECT entity_id FROM cache_v4_media_entities WHERE entity_id NOT IN "
        "(SELECT head_entity_id FROM cache_v4_source_frontiers) LIMIT 1"
    ).fetchone()
    assert other is not None
    with connection:
        connection.execute(
            "UPDATE cache_v4_source_frontiers SET head_entity_id=? WHERE source_id=(SELECT source_id FROM cache_v4_source_frontiers LIMIT 1)",
            (int(other[0]),),
        )
    connection.close()
    with pytest.raises(RuntimeError, match="source frontier mismatch"):
        certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)


def test_certification_rejects_registered_collection_mismatch(tmp_path: Path) -> None:
    source, target = _migrate(tmp_path)
    connection = sqlite3.connect(target)
    with connection:
        connection.execute(
            "UPDATE cache_v4_ytdlp_collections SET tags_json='[\"corrupted\"]' WHERE tags_json IS NOT NULL"
        )
    connection.close()
    with pytest.raises(RuntimeError, match="registered collection mismatch"):
        certify_v3_to_v4(source, target, mode=MigrationVerificationMode.FULL)


def test_semantic_mismatch_during_target_validation_blocks_finalisation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    from yt_media_tools import cache_v3_to_v4_migration as migration

    original = migration._build_bulk_indexes

    def build_then_corrupt(context: MigrationContext, events: MigrationEventStream) -> None:
        original(context, events)
        connection = sqlite3.connect(context.destination_path)
        with connection:
            connection.execute("UPDATE cache_v4_ytdlp_metadata SET title='corrupted'")
        connection.close()

    monkeypatch.setattr(migration, "_build_bulk_indexes", build_then_corrupt)
    with pytest.raises(Exception, match="registered metadata mismatch"):
        execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())

    connection = sqlite3.connect(target)
    try:
        meta = dict(connection.execute("SELECT key, value FROM cache_meta"))
        assert meta["schema_version"] == "3"
        assert meta["migration_state"] == "incomplete"
    finally:
        connection.close()


def test_migration_preserves_recorded_timestamp_text_precision(tmp_path: Path) -> None:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(FIXTURE, source)
    connection = sqlite3.connect(source)
    row = connection.execute(
        "SELECT source_url, video_id FROM metadata_records ORDER BY fetched_at DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    precise = "2026-01-02T03:04:05.12+00:00"
    with connection:
        connection.execute(
            "UPDATE metadata_records SET fetched_at=? WHERE source_url=? AND video_id=?",
            (precise, str(row[0]), str(row[1])),
        )
    connection.close()

    result = execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())
    assert result.succeeded
    connection = sqlite3.connect(target)
    try:
        acquisition = connection.execute(
            "SELECT last_success_at FROM cache_v4_acquisition_state a "
            "JOIN cache_v4_media_entities e USING(entity_id) WHERE e.external_id=?",
            (str(row[1]),),
        ).fetchone()
        assert acquisition == (precise,)
    finally:
        connection.close()
