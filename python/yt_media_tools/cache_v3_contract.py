"""Frozen structural validity contract for durable cache-v3 migration."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .sqlite import load_statement


@dataclass(frozen=True)
class V3ContractViolation:
    """One independently useful reason a database is outside the v3 contract."""

    code: str
    detail: str


_TABLE_COLUMNS = {
    "cache_meta": (("key", "TEXT", 0, 1), ("value", "TEXT", 1, 0)),
    "metadata_records": (
        ("source_url", "TEXT", 1, 1),
        ("video_id", "TEXT", 1, 2),
        ("fetched_at", "TEXT", 1, 0),
        ("raw_json", "TEXT", 1, 0),
    ),
    "source_observations": (
        ("source_url", "TEXT", 0, 1),
        ("source_kind", "TEXT", 1, 0),
        ("last_observed_at", "TEXT", 1, 0),
        ("observed_entries", "INTEGER", 1, 0),
    ),
    "source_entries": (
        ("source_url", "TEXT", 1, 1),
        ("video_id", "TEXT", 1, 2),
        ("source_index", "INTEGER", 1, 0),
        ("observed_at", "TEXT", 1, 0),
    ),
    "source_coverage": (
        ("source_url", "TEXT", 0, 1),
        ("source_kind", "TEXT", 1, 0),
        ("observed_at", "TEXT", 1, 0),
        ("observed_entries", "INTEGER", 1, 0),
        ("cached_entries", "INTEGER", 1, 0),
        ("complete", "INTEGER", 1, 0),
        ("reason", "TEXT", 1, 0),
    ),
    "source_frontiers": (
        ("source_url", "TEXT", 0, 1),
        ("source_kind", "TEXT", 1, 0),
        ("verified_at", "TEXT", 1, 0),
        ("known_entries", "INTEGER", 1, 0),
        ("head_video_id", "TEXT", 1, 0),
        ("overlap_confirmations", "INTEGER", 1, 0),
    ),
}

_REQUIRED_INDEXES = {
    "metadata_records_video_id": ("metadata_records", ("video_id",)),
    "source_entries_order": ("source_entries", ("source_url", "source_index")),
}


def _parse_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def _table_columns(db: sqlite3.Connection, table: str) -> tuple[tuple[str, str, int, int], ...]:
    return tuple(
        (str(row[1]), str(row[2]).upper(), int(row[3]), int(row[5]))
        for row in db.execute(f"PRAGMA table_info({table})")
    )


def validate_v3_database(path: Path) -> tuple[V3ContractViolation, ...]:
    """Return structural v3 contract violations without modifying the database."""
    violations: list[V3ContractViolation] = []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        integrity = db.execute(load_statement("common/integrity_check")).fetchone()
        if integrity != ("ok",):
            violations.append(V3ContractViolation("sqlite-integrity", str(integrity[0]) if integrity else "no result"))
            return tuple(violations)

        for table, expected in _TABLE_COLUMNS.items():
            actual = _table_columns(db, table)
            if actual != expected:
                violations.append(
                    V3ContractViolation("schema-shape", f"{table}: expected {expected!r}, found {actual!r}")
                )

        if any(item.code == "schema-shape" for item in violations):
            return tuple(violations)

        version_rows = db.execute(load_statement("common/cache_schema_version")).fetchall()
        if version_rows != [("3",)]:
            violations.append(
                V3ContractViolation("schema-version", f"expected one schema_version=3 row, found {version_rows!r}")
            )

        for name, (table, expected_columns) in _REQUIRED_INDEXES.items():
            row = db.execute(load_statement("common/schema_index_table"), (name,)).fetchone()
            if row != (table,):
                violations.append(V3ContractViolation("schema-index", f"missing or misplaced index {name}"))
                continue
            columns = tuple(str(item[2]) for item in db.execute(f"PRAGMA index_info({name})"))
            if columns != expected_columns:
                violations.append(
                    V3ContractViolation("schema-index", f"{name}: expected {expected_columns!r}, found {columns!r}")
                )

        for source_url, video_id, fetched_at, raw_json in db.execute(load_statement("cache_v3/v3_metadata_records")):
            if not _parse_timestamp(fetched_at):
                violations.append(
                    V3ContractViolation("metadata-timestamp", f"{source_url!r}/{video_id!r} has invalid fetched_at")
                )
            try:
                record = json.loads(raw_json)
            except (json.JSONDecodeError, TypeError):
                record = None
            if not isinstance(record, dict):
                violations.append(
                    V3ContractViolation(
                        "metadata-json-object", f"{source_url!r}/{video_id!r} raw_json is not a JSON object"
                    )
                )

        timestamp_queries = (
            ("source-observation-timestamp", load_statement("cache_v3/v3_observation_timestamps")),
            ("source-entry-timestamp", load_statement("cache_v3/v3_entry_timestamps")),
            ("source-coverage-timestamp", load_statement("cache_v3/v3_coverage_timestamps")),
            ("source-frontier-timestamp", load_statement("cache_v3/v3_frontier_timestamps")),
        )
        for code, query in timestamp_queries:
            for identity, value in db.execute(query):
                if not _parse_timestamp(value):
                    violations.append(V3ContractViolation(code, f"{identity!r} has an invalid timestamp"))

        for (source_url,) in db.execute(load_statement("cache_v3/v3_entry_sources")):
            indexes = [
                int(row[0])
                for row in db.execute(
                    load_statement("cache_v3/v3_entry_indexes"),
                    (source_url,),
                )
            ]
            expected = list(range(1, len(indexes) + 1))
            if indexes != expected:
                violations.append(
                    V3ContractViolation(
                        "source-entry-order", f"{source_url!r}: expected indexes {expected!r}, found {indexes!r}"
                    )
                )

        for source_url, known_entries, head_video_id in db.execute(load_statement("cache_v3/v3_frontiers")):
            rows = db.execute(load_statement("cache_v3/v3_ordered_entry_ids"), (source_url,)).fetchall()
            ids = [str(row[0]) for row in rows]
            if not ids:
                violations.append(
                    V3ContractViolation("frontier-order", f"{source_url!r}: frontier has no stored source ordering")
                )
            elif int(known_entries) != len(ids) or str(head_video_id) != ids[0]:
                violations.append(
                    V3ContractViolation(
                        "frontier-order",
                        f"{source_url!r}: frontier ({known_entries!r}, {head_video_id!r}) disagrees with stored ordering ({len(ids)!r}, {ids[0]!r})",
                    )
                )
    finally:
        db.close()
    return tuple(violations)
