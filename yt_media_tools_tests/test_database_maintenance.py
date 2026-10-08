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
