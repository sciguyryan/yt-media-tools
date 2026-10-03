"""Permanent historical acceptance tests for the v3-to-v4 cache transition."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sqlite3

import pytest

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_support import MigrationEventStream, MigrationLog, run_logged_transition
from yt_media_tools.cache_v3_to_v4_migration import execute_v3_to_v4


FIXTURES = Path(__file__).parent / "fixtures" / "cache_v3"
V3_FIXTURE = FIXTURES / "canonical-valid-v3.sqlite3"
EXPECTED_V4 = FIXTURES / "canonical-valid-v4-expected.json"


def _migrate(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    shutil.copy2(V3_FIXTURE, source)
    result = execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())
    assert result.succeeded
    return source, target


def test_canonical_v3_fixture_matches_independently_authored_v4_expectations(tmp_path: Path) -> None:
    _, target = _migrate(tmp_path)
    expected = json.loads(EXPECTED_V4.read_text())
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        entities = sorted(
            str(row["external_id"]) for row in connection.execute("SELECT external_id FROM cache_v4_media_entities")
        )
        assert entities == expected["entities"]

        metadata: dict[str, dict[str, object]] = {}
        for external_id, fields in expected["latest_registered_metadata"].items():
            row = connection.execute(
                "SELECT m.* FROM cache_v4_ytdlp_metadata m JOIN cache_v4_media_entities e USING(entity_id) WHERE e.external_id=?",
                (external_id,),
            ).fetchone()
            assert row is not None
            metadata[external_id] = {field: row[field] for field in fields}
        for external_id, fields in expected["latest_registered_metadata"].items():
            actual = metadata[external_id]
            for field, value in fields.items():
                if isinstance(value, bool):
                    assert bool(actual[field]) is value
                else:
                    assert actual[field] == value

        times = {
            str(row["external_id"]): str(row["last_success_at"])
            for row in connection.execute(
                "SELECT e.external_id, a.last_success_at FROM cache_v4_acquisition_state a JOIN cache_v4_media_entities e USING(entity_id)"
            )
        }
        assert times == expected["latest_acquisition_times"]

        entries: dict[str, list[str]] = {}
        for row in connection.execute(
            "SELECT s.source_url, e.external_id FROM cache_v4_source_entries se "
            "JOIN cache_v4_sources s USING(source_id) JOIN cache_v4_media_entities e USING(entity_id) "
            "ORDER BY s.source_url, se.source_index"
        ):
            entries.setdefault(str(row["source_url"]), []).append(str(row["external_id"]))
        assert entries == expected["source_entries"]

        coverage = {}
        for row in connection.execute(
            "SELECT s.source_url, c.observed_entries, c.cached_entries, c.complete, c.reason "
            "FROM cache_v4_source_coverage c JOIN cache_v4_sources s USING(source_id)"
        ):
            coverage[str(row["source_url"])] = {
                "observed_entries": int(row["observed_entries"]),
                "cached_entries": int(row["cached_entries"]),
                "complete": bool(row["complete"]),
                "reason": str(row["reason"]),
            }
        assert coverage == expected["source_coverage"]

        frontiers = {}
        for row in connection.execute(
            "SELECT s.source_url, f.known_entries, e.external_id AS head_video_id, f.overlap_confirmations "
            "FROM cache_v4_source_frontiers f JOIN cache_v4_sources s USING(source_id) "
            "JOIN cache_v4_media_entities e ON e.entity_id=f.head_entity_id"
        ):
            frontiers[str(row["source_url"])] = {
                "known_entries": int(row["known_entries"]),
                "head_video_id": str(row["head_video_id"]),
                "overlap_confirmations": int(row["overlap_confirmations"]),
            }
        assert frontiers == expected["source_frontiers"]

        collections = {}
        for row in connection.execute(
            "SELECT e.external_id, c.tags_json, c.categories_json, c.formats_json, c.chapters_json, c.thumbnails_json "
            "FROM cache_v4_ytdlp_collections c JOIN cache_v4_media_entities e USING(entity_id)"
        ):
            values = {}
            for name in ("tags", "categories", "formats", "chapters", "thumbnails"):
                payload = row[f"{name}_json"]
                if payload is not None:
                    values[name] = json.loads(str(payload))
            if values:
                collections[str(row["external_id"])] = values
        assert collections == expected["registered_collections"]
        tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "cache_v4_raw_compatibility" not in tables
        assert "cache_v4_raw_migration_accounting" not in tables
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        (
            "UPDATE source_entries SET source_index=0 WHERE rowid=(SELECT rowid FROM source_entries LIMIT 1)",
            "source-entry-order",
        ),
        (
            "UPDATE metadata_records SET raw_json='[]' WHERE rowid=(SELECT rowid FROM metadata_records LIMIT 1)",
            "metadata-json-object",
        ),
        (
            "UPDATE source_frontiers SET head_video_id='missing-history' WHERE rowid=(SELECT rowid FROM source_frontiers LIMIT 1)",
            "frontier-order",
        ),
    ],
)
def test_invalid_historical_v3_states_are_rejected_before_destination_creation(
    tmp_path: Path, mutation: str, expected_code: str
) -> None:
    source = tmp_path / "invalid-v3.sqlite3"
    target = tmp_path / "v4.sqlite3"
    shutil.copy2(V3_FIXTURE, source)
    connection = sqlite3.connect(source)
    with connection:
        connection.execute(mutation)
    connection.close()

    with pytest.raises(Exception, match=expected_code):
        execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())
    assert not target.exists()


def test_interrupted_logged_migration_keeps_destination_incomplete_and_restart_requires_disposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    log = MigrationLog(tmp_path / "migration.jsonl")
    shutil.copy2(V3_FIXTURE, source)

    from yt_media_tools import cache_v3_to_v4_migration as migration

    original = migration._populate_v4

    def populate_then_interrupt(context: MigrationContext, events: MigrationEventStream) -> None:
        original(context, events)
        raise KeyboardInterrupt

    monkeypatch.setattr(migration, "_populate_v4", populate_then_interrupt)
    with pytest.raises(KeyboardInterrupt):
        run_logged_transition(
            MigrationContext(source, target, 3, 4),
            execute_v3_to_v4,
            log=log,
        )

    connection = sqlite3.connect(target)
    try:
        meta = dict(connection.execute("SELECT key, value FROM cache_meta"))
        assert meta["schema_version"] == "3"
        assert meta["migration_state"] == "incomplete"
    finally:
        connection.close()
    assert json.loads(log.path.read_text().splitlines()[-1])["status"] == "interrupted"

    with pytest.raises(Exception, match="destination already exists"):
        execute_v3_to_v4(MigrationContext(source, target, 3, 4), MigrationEventStream())


def test_permanent_migration_log_contains_no_historical_payload_or_secret_material(tmp_path: Path) -> None:
    source = tmp_path / "metadata.sqlite3"
    target = tmp_path / "metadata-v4.sqlite3"
    log = MigrationLog(tmp_path / "migration.jsonl")
    shutil.copy2(V3_FIXTURE, source)

    result = run_logged_transition(
        MigrationContext(source, target, 3, 4),
        execute_v3_to_v4,
        log=log,
    )
    assert result.succeeded
    text = log.path.read_text()
    forbidden = (
        "discard-me",
        "signed?token=",
        "Café 東京",
        "Shared from videos",
        '"formats"',
        '"headers"',
        '"cookies"',
        '"raw_json"',
        '"payload_json"',
    )
    assert not any(value in text for value in forbidden)
    records = [json.loads(line) for line in text.splitlines()]
    assert records[0]["record"] == "start"
    assert records[-1]["record"] == "finish"
    assert records[-1]["status"] == "complete"
