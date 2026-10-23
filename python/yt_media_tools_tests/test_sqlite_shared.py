"""Shared SQLite resources and the collection-state integration contract."""

from __future__ import annotations

import sqlite3

import pytest

from pathlib import Path

from yt_media_tools.collection_state import CollectionState
from yt_media_tools.sqlite import load_statement, open_read_only, scalar


def test_statement_resources_do_not_depend_on_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    statement = load_statement("collection_state/create_completed_targets")
    assert "CREATE TABLE completed_targets" in statement
    assert load_statement("collection_state/create_completed_targets") == statement


@pytest.mark.parametrize("name", ["../cache", "/etc/passwd", "collection_state/../../cache", "", "common/x.sql"])
def test_statement_names_cannot_escape_resource_package(name):
    with pytest.raises(ValueError, match="invalid SQLite statement name"):
        load_statement(name)


def test_unknown_statement_fails_explicitly():
    with pytest.raises(ValueError, match="unknown SQLite statement"):
        load_statement("common/unknown")


def test_read_only_does_not_create_database(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        open_read_only(path)
    assert not path.exists()


def test_read_only_rejects_writes_and_supports_row_factory(tmp_path):
    path = tmp_path / "existing.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE values_table (value TEXT)")
        connection.execute("INSERT INTO values_table VALUES (?)", ("example",))
    with open_read_only(path, rows=True) as connection:
        assert scalar(connection, "SELECT value FROM values_table") == "example"
        assert connection.execute("SELECT value FROM values_table").fetchone()["value"] == "example"
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM values_table")
        with pytest.raises(ValueError, match="no rows"):
            scalar(connection, "SELECT value FROM values_table WHERE value = ?", ("absent",))


def test_collection_state_schema_and_observation_survive_reopen(tmp_path):
    state = CollectionState(tmp_path)
    identity = "yt-sql:sha256:" + "a" * 64
    state.record(identity, "one")
    state.record_observation(identity, ["one", "two", "one"])
    assert state.completed(identity) == {"one"}
    assert state.observation(identity) == (1, state.observation(identity)[1], 3)
    assert CollectionState(tmp_path).completed(identity) == {"one"}
    state.clear(identity)
    assert state.completed(identity) == set()
    with sqlite3.connect(state.path) as connection:
        assert scalar(connection, "PRAGMA user_version") == 2
        assert scalar(connection, load_statement("common/integrity_check")) == "ok"


def test_statements_use_the_single_common_sqlite_tree():
    root = Path(__file__).resolve().parents[2]
    statement = root / "common/sqlite/statements/collection_state/select_completed.sql"
    assert statement.is_file()
    assert load_statement("collection_state/select_completed") == statement.read_text(encoding="utf-8").strip()
    assert not (root / "python/yt_media_tools/sqlite/statements/collection_state").exists()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("page_size", 4096),
        ("page_count", 0),
        ("freelist_count", 0),
        ("auto_vacuum", 0),
    ],
)
def test_canonical_sqlite_measurement_statements(tmp_path, name, expected):
    """Shared inspection statements retain SQLite's native integer results."""
    path = tmp_path / "measurement.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE example (value TEXT)")
        result = scalar(connection, load_statement(f"common/{name}"))
    if name == "page_count":
        assert isinstance(result, int) and result > expected
    elif name == "page_size":
        assert isinstance(result, int) and result > 0
    else:
        assert result == expected


def test_canonical_measurements_have_no_duplicated_inline_reads():
    """Consumers use the canonical inspection SQL rather than copied PRAGMAs."""
    package = Path(__file__).resolve().parents[1] / "yt_media_tools"
    for module in ("database_maintenance.py", "cache_status.py", "cache_v3_to_v4_analysis.py"):
        source = (package / module).read_text(encoding="utf-8")
        for name in ("page_size", "page_count", "freelist_count", "auto_vacuum"):
            assert f'connection.execute("PRAGMA {name}")' not in source


@pytest.mark.parametrize(
    ("name", "parameters"),
    [
        ("cache_v4/insert_entity", 2),
        ("cache_v4/select_entity", 2),
        ("cache_v4/select_provider_registration", 1),
        ("cache_v4/select_acquisition_group", 2),
        ("cache_v4/select_last_attempt", 3),
    ],
)
def test_cache_v4_statements_preserve_positional_parameter_contract(name, parameters):
    """The shared cache statements retain their existing binding arity."""
    sql = load_statement(name)
    assert sql.count("?") == parameters
    assert sql.rstrip().endswith(";")


@pytest.mark.parametrize(
    ("name", "parameters"),
    [
        ("registry_revision", 0),
        ("registry_insert_revision", 1),
        ("registry_reset_providers", 0),
        ("registry_reset_groups", 0),
        ("registry_reset_fields", 0),
        ("registry_find_provider", 1),
        ("registry_find_field", 2),
    ],
)
def test_cache_v4_registry_statements_preserve_bindings(name, parameters):
    """Registry statements retain the existing positional parameter contracts."""
    statement = load_statement(f"cache_v4/{name}")
    assert statement.count("?") == parameters
    assert statement.endswith(";")


@pytest.mark.parametrize(
    ("statement_name", "table_name", "parameters"),
    [
        ("registry_find_provider", "cache_v4_providers", ("missing",)),
        ("registry_find_field", "cache_v4_fields", (0, "missing")),
    ],
)
def test_registry_explicit_projections_preserve_schema_column_order(statement_name, table_name, parameters):
    """Explicit projections must retain the original SELECT * row contract."""
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(load_statement("cache_v4/registry_schema"))
        expected = tuple(row[1] for row in connection.execute(f"PRAGMA table_info({table_name})"))
        cursor = connection.execute(load_statement(f"cache_v4/{statement_name}"), parameters)
        assert tuple(column[0] for column in cursor.description) == expected


def test_registry_join_statements_retain_expected_join_semantics():
    """Join qualification must not change the registry's provider/field relationships."""
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript(load_statement("cache_v4/registry_schema"))
        connection.execute(
            "INSERT INTO cache_v4_providers "
            "(provider_key, registration_order, schema_revision, metadata_table, applicability_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("provider-a", 1, 1, "metadata_a", "{}"),
        )
        provider_id = connection.execute("SELECT provider_id FROM cache_v4_providers").fetchone()[0]
        connection.execute(
            "INSERT INTO cache_v4_acquisition_groups (provider_id, group_key, registration_order) VALUES (?, ?, ?)",
            (provider_id, "group-a", 1),
        )
        group_id = connection.execute("SELECT acquisition_group_id FROM cache_v4_acquisition_groups").fetchone()[0]
        connection.execute(
            "INSERT INTO cache_v4_fields "
            "(provider_id, field_name, storage_name, acquisition_group_id, registration_order, "
            "type_json, default_freshness_mode, freshness_mode_override) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (provider_id, "title", "title", group_id, 1, '"string"', "always", "always"),
        )
        assert (
            connection.execute(
                load_statement("cache_v4/registry_field_id_by_provider_and_name"),
                ("provider-a", "title"),
            ).fetchone()
            is not None
        )
        assert (
            connection.execute(
                load_statement("cache_v4/registry_field_freshness_overrides"),
                ("provider-a",),
            ).fetchone()["field_name"]
            == "title"
        )
        assert (
            connection.execute(load_statement("cache_v4/registry_shared_field_type_claims")).fetchone()["provider_key"]
            == "provider-a"
        )
        assert (
            connection.execute(
                load_statement("cache_v4/select_acquisition_group"),
                ("provider-a", "group-a"),
            ).fetchone()["acquisition_group_id"]
            == group_id
        )
        assert (
            connection.execute(
                load_statement("cache_v4/registry_field_provider_candidates"),
                ("title",),
            ).fetchone()["field_name"]
            == "title"
        )


def test_shared_cache_discovery_statements_preserve_metadata_and_index_contract(tmp_path):
    """Read-only discovery SQL retains column order and bound index names."""
    path = tmp_path / "discovery.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE cache_meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute("INSERT INTO cache_meta VALUES ('schema_version', '3')")
        connection.execute("INSERT INTO cache_meta VALUES ('migration_state', 'complete')")
        assert dict(connection.execute(load_statement("common/cache_meta_pairs"))) == {
            "schema_version": "3",
            "migration_state": "complete",
        }
        assert connection.execute(load_statement("common/cache_schema_version")).fetchall() == [("3",)]
        assert connection.execute(
            load_statement("common/schema_index_table"), ("sqlite_autoindex_cache_meta_1",)
        ).fetchone() == ("cache_meta",)
        assert connection.execute(load_statement("common/schema_index_table"), ("absent",)).fetchone() is None
