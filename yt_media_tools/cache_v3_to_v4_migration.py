"""Durable side-by-side migration from the legacy v3 cache to cache v4."""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3

from .cache import MetadataCache, initialise_v4_cache
from .cache_v3_contract import validate_v3_database
from .cache_v3_to_v4_analysis import estimate_v4_space
from .cache_v3_to_v4_verification import MigrationVerificationMode, certify_v3_to_v4
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
# Measured in issue #135 against deterministic small, normal and large migration shapes.
# This remains a conservative transaction bound; tuning showed population dominates runtime,
# while transaction batching is not a material source of storage churn after fresh-destination construction.
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


def _initialise_destination(context: MigrationContext, events: MigrationEventStream) -> None:
    """Create a fresh incomplete v4 destination without copying legacy v3 pages."""
    initialise_v4_cache(context.destination_path)
    connection = sqlite3.connect(context.destination_path)
    try:
        with connection:
            connection.execute(
                "UPDATE cache_meta SET value = ? WHERE key = 'schema_version'", (str(V3_SCHEMA_VERSION),)
            )
            connection.execute("UPDATE cache_meta SET value = 'incomplete' WHERE key = 'migration_state'")
    finally:
        connection.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase initialise v4 destination",
            kind="progress",
            message="Created a fresh incomplete v4 migration destination",
        )
    )


def _populate_source_state(context: MigrationContext, events: MigrationEventStream) -> None:
    """Import v3 source state directly into the fresh v4 destination."""
    source = sqlite3.connect(f"file:{context.source_path.resolve().as_posix()}?mode=ro", uri=True)
    destination = sqlite3.connect(context.destination_path)
    source.row_factory = sqlite3.Row
    destination.row_factory = sqlite3.Row
    try:
        kinds: dict[str, str] = {}
        for table in ("source_observations", "source_coverage", "source_frontiers"):
            for row in source.execute(f"SELECT source_url, source_kind FROM {table}"):
                kinds.setdefault(str(row["source_url"]), str(row["source_kind"]))
        urls = set(kinds)
        urls.update(str(row["source_url"]) for row in source.execute("SELECT DISTINCT source_url FROM source_entries"))
        with destination:
            for source_url in sorted(urls):
                destination.execute(
                    """INSERT INTO cache_v4_sources(source_url, source_kind, facet) VALUES (?, ?, '')
                    ON CONFLICT(source_url, facet) DO UPDATE SET source_kind = excluded.source_kind""",
                    (source_url, kinds.get(source_url, "unknown")),
                )
                source_id = int(
                    destination.execute(
                        "SELECT source_id FROM cache_v4_sources WHERE source_url = ? AND facet = ''", (source_url,)
                    ).fetchone()["source_id"]
                )
                observation = source.execute(
                    "SELECT last_observed_at, observed_entries FROM source_observations WHERE source_url = ?",
                    (source_url,),
                ).fetchone()
                if observation is not None:
                    destination.execute(
                        "INSERT INTO cache_v4_source_observations(source_id, last_observed_at, observed_entries) VALUES (?, ?, ?)",
                        (source_id, observation["last_observed_at"], observation["observed_entries"]),
                    )
                entries = source.execute(
                    "SELECT video_id FROM source_entries WHERE source_url = ? ORDER BY source_index, video_id",
                    (source_url,),
                ).fetchall()
                for index, row in enumerate(entries):
                    video_id = str(row["video_id"])
                    destination.execute(
                        "INSERT INTO cache_v4_media_entities(service, external_id) VALUES ('youtube', ?) "
                        "ON CONFLICT(service, external_id) DO NOTHING",
                        (video_id,),
                    )
                    entity_id = int(
                        destination.execute(
                            "SELECT entity_id FROM cache_v4_media_entities WHERE service = 'youtube' AND external_id = ?",
                            (video_id,),
                        ).fetchone()["entity_id"]
                    )
                    destination.execute(
                        "INSERT INTO cache_v4_source_entries(source_id, entity_id, source_index) VALUES (?, ?, ?)",
                        (source_id, entity_id, index),
                    )
                coverage = source.execute(
                    "SELECT observed_at, observed_entries, cached_entries, complete, reason FROM source_coverage WHERE source_url = ?",
                    (source_url,),
                ).fetchone()
                if coverage is not None:
                    destination.execute(
                        """INSERT INTO cache_v4_source_coverage(
                        source_id, observed_at, observed_entries, cached_entries, complete, reason
                        ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            source_id,
                            coverage["observed_at"],
                            coverage["observed_entries"],
                            coverage["cached_entries"],
                            coverage["complete"],
                            coverage["reason"],
                        ),
                    )
                frontier = source.execute(
                    "SELECT verified_at, known_entries, head_video_id, overlap_confirmations FROM source_frontiers WHERE source_url = ?",
                    (source_url,),
                ).fetchone()
                if frontier is not None:
                    head_id = str(frontier["head_video_id"])
                    destination.execute(
                        "INSERT INTO cache_v4_media_entities(service, external_id) VALUES ('youtube', ?) "
                        "ON CONFLICT(service, external_id) DO NOTHING",
                        (head_id,),
                    )
                    head_entity_id = int(
                        destination.execute(
                            "SELECT entity_id FROM cache_v4_media_entities WHERE service = 'youtube' AND external_id = ?",
                            (head_id,),
                        ).fetchone()["entity_id"]
                    )
                    destination.execute(
                        """INSERT INTO cache_v4_source_frontiers(
                        source_id, verified_at, known_entries, head_entity_id, overlap_confirmations
                        ) VALUES (?, ?, ?, ?, ?)""",
                        (
                            source_id,
                            frontier["verified_at"],
                            frontier["known_entries"],
                            head_entity_id,
                            frontier["overlap_confirmations"],
                        ),
                    )
    finally:
        destination.close()
        source.close()
    events.emit(
        MigrationEvent.create(
            context,
            stage="phase populate v4 source state",
            kind="progress",
            message=f"Migrated {len(urls)} source-state records into the v4 representation",
            completed=len(urls),
            total=len(urls),
        )
    )


def _populate_v4(context: MigrationContext, events: MigrationEventStream) -> None:
    migrated = 0
    source = sqlite3.connect(f"file:{context.source_path.resolve().as_posix()}?mode=ro", uri=True)
    cache = MetadataCache(context.destination_path)
    cache.connection = sqlite3.connect(context.destination_path)
    cache.connection.execute("PRAGMA foreign_keys = ON")
    cache.connection.execute("PRAGMA journal_mode = WAL")
    cache.connection.execute("PRAGMA synchronous = NORMAL")
    cache.connection.row_factory = sqlite3.Row
    cache.schema_version = V4_SCHEMA_VERSION
    try:
        rows = source.execute(
            "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records ORDER BY fetched_at, source_url, video_id"
        )
        total = int(source.execute("SELECT COUNT(*) FROM metadata_records").fetchone()[0])
        for batch in bounded_batches(rows, _MIGRATION_BATCH_SIZE):
            try:
                cache._db().execute("BEGIN")
                for source_url, video_id, fetched_at, raw_json in batch:
                    record = json.loads(str(raw_json))
                    accepted = cache._normalise_record_into_v4(
                        str(source_url),
                        record,
                        acquired_at=datetime.fromisoformat(str(fetched_at)),
                        entity_video_id=str(video_id),
                        commit=False,
                        historical_timestamp=str(fetched_at),
                    )
                    if not accepted:
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
    finally:
        cache.close()
        source.close()
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
            "cache_v4_source_observations",
            "cache_v4_source_entries",
            "cache_v4_source_coverage",
            "cache_v4_source_frontiers",
            "cache_v4_ytdlp_collections",
        }
        missing = required - tables
        if missing:
            raise RuntimeError(f"destination is missing required v4 tables: {', '.join(sorted(missing))}")
        state = connection.execute("SELECT value FROM cache_meta WHERE key = 'migration_state'").fetchone()
        if state != ("incomplete",):
            raise RuntimeError("destination lost its incomplete migration marker before validation")
    finally:
        connection.close()
    certify_v3_to_v4(context.source_path, context.destination_path, mode=MigrationVerificationMode.NORMAL)


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
            MigrationPhase("initialise v4 destination", _initialise_destination),
            MigrationPhase("defer bulk indexes", _defer_bulk_indexes),
            MigrationPhase("populate v4 source state", _populate_source_state),
            MigrationPhase("populate v4 representation", _populate_v4),
            MigrationPhase("build bulk indexes", _build_bulk_indexes),
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
