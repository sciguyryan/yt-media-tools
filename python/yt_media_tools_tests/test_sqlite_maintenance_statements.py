"""Contracts for the canonical cache-v4 maintenance statement resources."""

from __future__ import annotations

import sqlite3

import pytest

from yt_media_tools.sqlite import load_statement


@pytest.mark.parametrize(
    ("name", "parameters"),
    [
        ("maintenance_provider_for_planning", 1),
        ("maintenance_source_observations", 0),
        ("maintenance_table_exists", 1),
        ("maintenance_acquisition_entity_exists", 1),
        ("maintenance_source_entry_entity_exists", 1),
        ("maintenance_source_frontier_entity_exists", 1),
        ("maintenance_provider_metadata_tables", 0),
        ("maintenance_provider_for_execution", 1),
        ("maintenance_delete_acquisition_state", 2),
        ("maintenance_delete_ytdlp_collection", 1),
        ("maintenance_source_entry_entities", 1),
        ("maintenance_source_frontier_head", 1),
        ("maintenance_delete_source", 1),
        ("maintenance_delete_unreferenced_entity", 1),
    ],
)
def test_maintenance_statement_parameter_contract(name: str, parameters: int) -> None:
    sql = load_statement(f"cache_v4/{name}")
    assert sql.count("?") == parameters
    assert sqlite3.complete_statement(sql)


def test_maintenance_table_discovery_preserves_result_shape() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
        statement = load_statement("cache_v4/maintenance_table_exists")
        assert connection.execute(statement, ("sample",)).fetchone() == (1,)
        assert connection.execute(statement, ("absent",)).fetchone() is None
    finally:
        connection.close()
