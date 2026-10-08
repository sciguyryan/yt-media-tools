"""Read-only SQLite maintenance policy and measurement contract."""

import sqlite3

import pytest

from yt_media_tools.database_maintenance import (
    MaintenanceInspectionError,
    MaintenancePolicyError,
    decide_maintenance,
    default_policy,
    dry_run,
    inspect_database,
    load_policy,
    parse_policy,
)


def test_absent_default_and_explicit_missing(tmp_path):
    assert default_policy().strategy == "hybrid"
    with pytest.raises(MaintenancePolicyError):
        load_policy(tmp_path / "missing.toml")


@pytest.mark.parametrize(
    "text",
    [
        "schema_version = 2",
        "schema_version = 1\nunknown = true",
        "schema_version = 1\n[maintenance.full]\nautomatic = true",
        "schema_version = 1\n[maintenance.incremental]\nmax_pages_per_run = 0",
        "schema_version = 1\n[databases.metadata_cache]\nmin_free_ratio = 1.1",
        "schema_version = 1\n[maintenance]\nenabled = 1",
        "schema_version = 1\n[maintenance]\ntrigger = 'during-query'",
        "schema_version = 1\n[maintenance]\nstrategy = 'full'",
        "schema_version = 1\n[maintenance.incremental]\nmax_duration_seconds = -1",
        "schema_version = 1\n[databases.collection_state]\nmin_free_ratio = true",
        "schema_version = 1\n[databases.unknown]\nmin_free_ratio = 0.5",
        "[broken",
    ],
)
def test_invalid_policy_rejected(text):
    with pytest.raises(MaintenancePolicyError):
        parse_policy(text)


def test_explicit_policy(tmp_path):
    source = tmp_path / "database-maintenance.toml"
    source.write_text(
        "schema_version = 1\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0.0\n"
    )
    assert load_policy(source).databases["collection_state"].min_reclaimable_mib == 0


def test_inspection_and_dry_run_never_mutate(tmp_path):
    source = tmp_path / "collection.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute("CREATE TABLE records (payload TEXT)")
        connection.executemany("INSERT INTO records VALUES (?)", [("x" * 1000,)] * 200)
        connection.execute("DELETE FROM records")
    before = source.read_bytes()
    measurement = inspect_database(source)
    assert measurement.auto_vacuum == "incremental"
    assert measurement.freelist_count > 0
    policy = parse_policy(
        "schema_version = 1\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0.0\n"
    )
    decision = dry_run(source, "collection_state", policy)
    assert decision.eligible and decision.action == "incremental_vacuum"
    assert source.read_bytes() == before
    assert decide_maintenance(measurement, default_policy(), "metadata_cache").eligible is False


def test_non_incremental_database_is_not_silently_converted(tmp_path):
    source = tmp_path / "old.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE records (value INTEGER)")
    assert dry_run(source, "metadata_cache", default_policy()).action == "none"
    assert inspect_database(source).auto_vacuum == "none"


def test_missing_database_not_created(tmp_path):
    source = tmp_path / "absent.sqlite3"
    with pytest.raises(MaintenanceInspectionError):
        inspect_database(source)
    assert not source.exists()


def test_incremental_maintenance_reclaims_pages_and_preserves_records(tmp_path):
    from yt_media_tools.database_maintenance import incremental_maintenance

    source = tmp_path / "collection.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute("CREATE TABLE records (payload TEXT)")
        connection.executemany("INSERT INTO records VALUES (?)", [("x" * 1000,)] * 300)
        connection.execute("DELETE FROM records WHERE rowid > 10")
    policy = parse_policy(
        "schema_version = 1\n[maintenance.incremental]\nmax_pages_per_run = 10\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0\n"
    )
    before = inspect_database(source)
    result = incremental_maintenance(source, "collection_state", policy)
    after = inspect_database(source)
    assert result.status == "completed"
    assert 0 < result.pages_reclaimed <= 10
    assert after.freelist_count < before.freelist_count
    with sqlite3.connect(source) as connection:
        assert connection.execute("SELECT count(*) FROM records").fetchone()[0] == 10


def test_incremental_maintenance_never_converts_legacy_database(tmp_path):
    from yt_media_tools.database_maintenance import incremental_maintenance

    source = tmp_path / "old.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE records (value INTEGER)")
    before = source.read_bytes()
    result = incremental_maintenance(source, "collection_state")
    assert result.status == "skipped"
    assert source.read_bytes() == before


def test_incremental_maintenance_defers_missing_database(tmp_path):
    from yt_media_tools.database_maintenance import incremental_maintenance

    source = tmp_path / "missing.sqlite3"
    assert incremental_maintenance(source, "collection_state").status == "deferred"
    assert not source.exists()


def test_incremental_maintenance_defers_under_write_contention(tmp_path):
    from yt_media_tools.database_maintenance import incremental_maintenance

    source = tmp_path / "contended.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.executemany("INSERT INTO records VALUES (?)", [("x" * 2000,)] * 100)
        connection.execute("DELETE FROM records")
    policy = parse_policy(
        "schema_version = 1\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0\n"
    )
    with sqlite3.connect(source) as writer:
        writer.execute("BEGIN IMMEDIATE")
        result = incremental_maintenance(source, "collection_state", policy)
        assert result.status == "deferred"
        assert result.pages_reclaimed == 0


def test_incremental_maintenance_respects_zero_elapsed_budget(tmp_path):
    from yt_media_tools.database_maintenance import incremental_maintenance

    source = tmp_path / "budget.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.executemany("INSERT INTO records VALUES (?)", [("x" * 2000,)] * 100)
        connection.execute("DELETE FROM records")
    policy = parse_policy(
        "schema_version = 1\n[databases.collection_state]\nmin_reclaimable_mib = 0\nmin_free_ratio = 0\n"
    )
    result = incremental_maintenance(source, "collection_state", policy, clock=iter([0, 10]).__next__)
    assert result.status == "completed"
    assert result.pages_reclaimed == 0
