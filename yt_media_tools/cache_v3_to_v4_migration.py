"""Durable side-by-side migration from the legacy v3 cache to cache v4."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from .cache import MetadataCache
from .cache_v3_contract import validate_v3_database
from .cache_v3_to_v4_analysis import estimate_v4_space
from .cache_migration import MigrationContext, MigrationTransition, MigrationTransitionResult
from .cache_migration_support import (
    MigrationEvent,
    MigrationEventStream,
    bounded_batches,
    check_disk_space,
    check_sqlite_integrity,
)
from .cache_migration_workflow import MigrationPhase, MigrationWorkflow, run_migration_workflow


V3_SCHEMA_VERSION = 3
V4_SCHEMA_VERSION = 4
_REQUIRED_V3_TABLES = frozenset(
    {"cache_meta", "metadata_records", "source_observations", "source_entries", "source_coverage", "source_frontiers"}
)
_LEGACY_V3_TABLES = tuple(sorted(_REQUIRED_V3_TABLES - {"cache_meta"}))
_MIGRATION_BATCH_SIZE = 500
_DEFERRED_V4_INDEXES = (("cache_v4_source_entries_entity", "cache_v4_source_entries", "entity_id"),)


def _read_schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT value FROM cache_meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        raise RuntimeError("metadata cache has no schema version")
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("metadata cache has an invalid schema version") from exc


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _validate_v3_source(context: MigrationContext) -> None:
    if context.source_version != V3_SCHEMA_VERSION or context.target_version != V4_SCHEMA_VERSION:
        raise RuntimeError("v3-to-v4 migration received an unexpected schema hop")
    violations = validate_v3_database(context.source_path)
    if violations:
        summary = "; ".join(f"{item.code}: {item.detail}" for item in violations)
        raise RuntimeError(f"source database is outside the cache-v3 migration contract: {summary}")


def _preflight_destination_space(context: MigrationContext, events: MigrationEventStream) -> None:
    estimate = estimate_v4_space(context.source_path)
    preflight = check_disk_space(context.destination_path, estimate.required_bytes)
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase preflight destination space",
            kind="progress",
            message=(
                f"Estimated {preflight.required_bytes} bytes for the v4 destination; "
                f"{preflight.available_bytes} bytes are available"
            ),
            completed=preflight.available_bytes,
            total=preflight.required_bytes,
        )
    )
    if not preflight.sufficient:
        raise RuntimeError(
            f"insufficient destination disk space: need {preflight.required_bytes} bytes, "
            f"have {preflight.available_bytes} bytes"
        )


def _defer_bulk_indexes(context: MigrationContext, events: MigrationEventStream) -> None:
    connection = sqlite3.connect(context.destination_path)
    try:
        with connection:
            for index_name, _, _ in _DEFERRED_V4_INDEXES:
                connection.execute(f'DROP INDEX IF EXISTS "{index_name}"')
    finally:
        connection.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase defer bulk indexes",
            kind="progress",
            message=f"Deferred {len(_DEFERRED_V4_INDEXES)} v4 bulk index until after population",
            completed=len(_DEFERRED_V4_INDEXES),
            total=len(_DEFERRED_V4_INDEXES),
        )
    )


def _build_bulk_indexes(context: MigrationContext, events: MigrationEventStream) -> None:
    connection = sqlite3.connect(context.destination_path)
    try:
        with connection:
            for index_name, table_name, column_name in _DEFERRED_V4_INDEXES:
                connection.execute(f'CREATE INDEX IF NOT EXISTS "{index_name}" ON "{table_name}"("{column_name}")')
    finally:
        connection.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase build bulk indexes",
            kind="progress",
            message=f"Built {len(_DEFERRED_V4_INDEXES)} deferred v4 bulk index",
            completed=len(_DEFERRED_V4_INDEXES),
            total=len(_DEFERRED_V4_INDEXES),
        )
    )


def _copy_source(context: MigrationContext, events: MigrationEventStream) -> None:
    if context.destination_path.exists():
        raise RuntimeError("migration destination already exists")
    context.destination_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(f"file:{context.source_path.resolve().as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(context.destination_path)
    try:
        source.backup(destination)
        destination.execute("INSERT OR REPLACE INTO cache_meta(key, value) VALUES('migration_state', 'incomplete')")
        destination.commit()
    finally:
        destination.close()
        source.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase copy v3 database",
            kind="progress",
            message="Copied the protected v3 source into the migration destination",
        )
    )


def _clear_transitional_v4_state(context: MigrationContext, events: MigrationEventStream) -> None:
    """Discard live-v3 bridge material so the durable migration rebuilds v4 from v3 facts."""
    connection = sqlite3.connect(context.destination_path)
    try:
        names = [
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'cache_v4_%'"
            ).fetchall()
        ]
        connection.execute("PRAGMA foreign_keys = OFF")
        with connection:
            for name in names:
                connection.execute(f'DROP TABLE "{name}"')
    finally:
        connection.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase reset transitional v4 state",
            kind="progress",
            message=f"Removed {len(names)} transitional v4 tables before rebuilding the durable target",
            completed=len(names),
            total=len(names),
        )
    )


def _populate_v4(context: MigrationContext, events: MigrationEventStream) -> None:
    migrated = 0
    with MetadataCache(context.destination_path) as cache:
        rows = cache._db().execute(
            "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records ORDER BY fetched_at, source_url, video_id"
        )
        total = int(cache._db().execute("SELECT COUNT(*) FROM metadata_records").fetchone()[0])
        for batch in bounded_batches(rows, _MIGRATION_BATCH_SIZE):
            try:
                cache._db().execute("BEGIN")
                for source_url, video_id, fetched_at, raw_json in batch:
                    record = json.loads(str(raw_json))
                    accounting = cache._normalise_record_into_v4(
                        str(source_url),
                        record,
                        acquired_at=datetime.fromisoformat(str(fetched_at)),
                        entity_video_id=str(video_id),
                        commit=False,
                    )
                    if accounting is None:
                        raise RuntimeError("v3 metadata record has no usable media identity")
                    migrated += 1
                cache._db().commit()
            except BaseException:
                cache._db().rollback()
                raise
            events.emit(
                MigrationEvent.create(
                    context,
                    stage="phase populate v4 representation",
                    kind="progress",
                    message=f"Migrated {migrated} detailed metadata records",
                    completed=migrated,
                    total=total,
                )
            )
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase populate v4 representation",
            kind="progress",
            message=f"Migrated {migrated} detailed metadata records into the v4 representation",
            completed=migrated,
            total=migrated,
        )
    )


def _remove_legacy_tables(context: MigrationContext, events: MigrationEventStream) -> None:
    connection = sqlite3.connect(context.destination_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            for table in _LEGACY_V3_TABLES:
                connection.execute(f'DROP TABLE "{table}"')
    finally:
        connection.close()


def _validate_v4_target(context: MigrationContext) -> None:
    connection = sqlite3.connect(context.destination_path)
    try:
        if check_sqlite_integrity(connection) != ("ok",):
            raise RuntimeError("destination SQLite integrity check failed")
        tables = _table_names(connection)
        if any(table in tables for table in _LEGACY_V3_TABLES):
            raise RuntimeError("destination still contains legacy v3 runtime tables")
        required = {
            "cache_v4_registry_meta",
            "cache_v4_providers",
            "cache_v4_media_entities",
            "cache_v4_ytdlp_metadata",
            "cache_v4_acquisition_state",
            "cache_v4_sources",
            "cache_v4_source_entries",
            "cache_v4_raw_compatibility",
            "cache_v4_raw_migration_accounting",
        }
        missing = required - tables
        if missing:
            raise RuntimeError(f"destination is missing required v4 tables: {', '.join(sorted(missing))}")
        state = connection.execute("SELECT value FROM cache_meta WHERE key = 'migration_state'").fetchone()
        if state != ("incomplete",):
            raise RuntimeError("destination lost its incomplete migration marker before validation")
    finally:
        connection.close()


def _finalise_v4_destination(context: MigrationContext) -> None:
    connection = sqlite3.connect(context.destination_path)
    try:
        with connection:
            connection.execute(
                "INSERT OR REPLACE INTO cache_meta(key, value) VALUES('schema_version', ?)",
                (str(V4_SCHEMA_VERSION),),
            )
            connection.execute("INSERT OR REPLACE INTO cache_meta(key, value) VALUES('migration_state', 'complete')")
    finally:
        connection.close()


def execute_v3_to_v4(context: MigrationContext, events: MigrationEventStream) -> MigrationTransitionResult:
    """Build and certify a new v4 database without modifying the v3 source."""
    workflow = MigrationWorkflow.create(
        validate_source=_validate_v3_source,
        phases=(
            MigrationPhase("preflight destination space", _preflight_destination_space),
            MigrationPhase("copy v3 database", _copy_source),
            MigrationPhase("reset transitional v4 state", _clear_transitional_v4_state),
            MigrationPhase("defer bulk indexes", _defer_bulk_indexes),
            MigrationPhase("populate v4 representation", _populate_v4),
            MigrationPhase("build bulk indexes", _build_bulk_indexes),
            MigrationPhase("remove legacy v3 tables", _remove_legacy_tables),
        ),
        validate_target=_validate_v4_target,
        finalise_destination=_finalise_v4_destination,
    )
    return run_migration_workflow(context, workflow, events)


def v3_to_v4_transition(events: MigrationEventStream) -> MigrationTransition:
    """Return the registered v3-to-v4 transition using the supplied event stream."""
    return MigrationTransition(
        V3_SCHEMA_VERSION,
        V4_SCHEMA_VERSION,
        lambda context: execute_v3_to_v4(context, events),
    )
