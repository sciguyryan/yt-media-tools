#!/usr/bin/env python3
"""Benchmark cache-v4 runtime resolution, retention and explicit compaction behaviour."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time


PROFILE_ENTITY_COUNTS = {"small": 100, "normal": 1_000, "large": 10_000, "huge": 50_000}
_RESOLUTION_REPETITIONS = 5
_NOW = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def _runtime_api() -> tuple[object, ...]:
    """Import project APIs after making direct script execution repository-aware."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from yt_media_tools.cache_compaction import compact_cache, measure_sqlite_storage
    from yt_media_tools.cache_entity_store import CacheV4EntityStore
    from yt_media_tools.cache_maintenance import (
        CacheMaintenanceAuthorisation,
        CacheRetentionPolicy,
        execute_cache_maintenance,
        plan_cache_retention,
    )
    from yt_media_tools.cache_registry import (
        AcquisitionGroupDefinition,
        FreshnessPolicy,
        ProviderApplicability,
        ProviderDefinition,
        ProviderFieldDefinition,
    )
    from yt_media_tools.cache_registry_store import CacheV4RegistryStore
    from yt_media_tools.query_types import QueryType

    return (
        compact_cache,
        measure_sqlite_storage,
        CacheV4EntityStore,
        CacheMaintenanceAuthorisation,
        CacheRetentionPolicy,
        execute_cache_maintenance,
        plan_cache_retention,
        AcquisitionGroupDefinition,
        FreshnessPolicy,
        ProviderApplicability,
        ProviderDefinition,
        ProviderFieldDefinition,
        CacheV4RegistryStore,
        QueryType,
    )


@dataclass(frozen=True)
class RuntimeBenchmarkResult:
    """Machine-readable runtime and maintenance reconciliation measurements."""

    profile: str
    entity_count: int
    resolution_calls: int
    resolution_seconds: float
    resolution_calls_per_second: float
    fallback_resolutions: int
    stale_fallback_resolutions: int
    retention_plan_seconds: float
    retention_execute_seconds: float
    selected_provider_contributions: int
    removed_provider_contributions: int
    collected_entities: int
    before_maintenance_bytes: int
    after_maintenance_bytes: int
    reusable_bytes_after_maintenance: int
    compaction_seconds: float
    compaction_performed: bool
    after_compaction_bytes: int


def _providers() -> tuple[object, object]:
    (
        _compact_cache,
        _measure_sqlite_storage,
        _CacheV4EntityStore,
        _CacheMaintenanceAuthorisation,
        _CacheRetentionPolicy,
        _execute_cache_maintenance,
        _plan_cache_retention,
        AcquisitionGroupDefinition,
        FreshnessPolicy,
        ProviderApplicability,
        ProviderDefinition,
        ProviderFieldDefinition,
        _CacheV4RegistryStore,
        QueryType,
    ) = _runtime_api()

    def provider(key: str) -> object:
        return ProviderDefinition(
            key=key,
            schema_revision=1,
            metadata_table=f"benchmark_provider_{key}",
            acquisition_groups=(AcquisitionGroupDefinition("basic-info"),),
            fields=(
                ProviderFieldDefinition(
                    name="title",
                    value_type=QueryType.scalar("string"),
                    acquisition_group="basic-info",
                    storage_name="title",
                    freshness=FreshnessPolicy.max_age(3600),
                ),
            ),
            applicability=ProviderApplicability(services=frozenset({"youtube"})),
        )

    return provider("primary"), provider("specialised")


def run_benchmark(path: Path, profile: str, entity_count: int) -> RuntimeBenchmarkResult:
    """Exercise provider resolution and the production maintenance/compaction paths."""
    (
        compact_cache,
        measure_sqlite_storage,
        CacheV4EntityStore,
        CacheMaintenanceAuthorisation,
        CacheRetentionPolicy,
        execute_cache_maintenance,
        plan_cache_retention,
        _AcquisitionGroupDefinition,
        _FreshnessPolicy,
        _ProviderApplicability,
        _ProviderDefinition,
        _ProviderFieldDefinition,
        CacheV4RegistryStore,
        _QueryType,
    ) = _runtime_api()
    primary, specialised = _providers()
    providers = (primary, specialised)

    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.row_factory = sqlite3.Row
    registry = CacheV4RegistryStore(connection)
    registry.reconcile(providers)
    registry.set_provider_policy("primary", priority=20)
    registry.set_provider_policy("specialised", priority=10)
    store = CacheV4EntityStore(connection, registry)
    store.initialise(providers)

    entity_ids: list[int] = []
    fallback_expected = 0
    stale_expected = 0
    old = _NOW - timedelta(days=90)
    fresh = _NOW - timedelta(minutes=10)
    stale = _NOW - timedelta(hours=2)

    for index in range(entity_count):
        entity = store.get_or_create_entity("youtube", f"benchmark-{index:08d}")
        entity_ids.append(entity.entity_id)
        mode = index % 4
        if mode == 0:
            store.write_provider_metadata(primary, entity.entity_id, {"title": f"Primary {index}"})
            store.record_acquisition_success(primary, entity.entity_id, "basic-info", acquired_at=fresh)
        elif mode == 1:
            store.write_provider_metadata(primary, entity.entity_id, {"title": None})
            store.record_acquisition_success(primary, entity.entity_id, "basic-info", acquired_at=fresh)
            store.write_provider_metadata(specialised, entity.entity_id, {"title": f"Specialised {index}"})
            store.record_acquisition_success(specialised, entity.entity_id, "basic-info", acquired_at=fresh)
            fallback_expected += 1
        elif mode == 2:
            store.write_provider_metadata(primary, entity.entity_id, {"title": f"Stale primary {index}"})
            store.record_acquisition_success(primary, entity.entity_id, "basic-info", acquired_at=stale)
            store.write_provider_metadata(specialised, entity.entity_id, {"title": f"Fresh specialised {index}"})
            store.record_acquisition_success(specialised, entity.entity_id, "basic-info", acquired_at=fresh)
            fallback_expected += 1
            stale_expected += 1
        else:
            store.write_provider_metadata(primary, entity.entity_id, {"title": f"Old {index}"})
            store.record_acquisition_success(primary, entity.entity_id, "basic-info", acquired_at=old)

    connection.commit()
    before = measure_sqlite_storage(connection, path)

    resolution_calls = entity_count * _RESOLUTION_REPETITIONS
    fallback_resolutions = 0
    stale_fallback_resolutions = 0
    started = time.perf_counter()
    for _ in range(_RESOLUTION_REPETITIONS):
        for index, entity_id in enumerate(entity_ids):
            resolved = store.resolve_field(providers, entity_id, "title", as_of=_NOW)
            if resolved.provider_key == "specialised":
                fallback_resolutions += 1
                if index % 4 == 2:
                    stale_fallback_resolutions += 1
    resolution_seconds = time.perf_counter() - started

    policy = CacheRetentionPolicy(provider_max_age=timedelta(days=30))
    started = time.perf_counter()
    plan = plan_cache_retention(connection, providers, policy, now=_NOW)
    retention_plan_seconds = time.perf_counter() - started
    started = time.perf_counter()
    result = execute_cache_maintenance(
        connection,
        providers,
        plan,
        authorisation=CacheMaintenanceAuthorisation.explicit(),
    )
    retention_execute_seconds = time.perf_counter() - started
    after_maintenance = measure_sqlite_storage(connection, path)

    started = time.perf_counter()
    compaction = compact_cache(connection, path)
    compaction_seconds = time.perf_counter() - started
    connection.close()

    if fallback_resolutions != fallback_expected * _RESOLUTION_REPETITIONS:
        raise RuntimeError("provider fallback count did not match the deterministic benchmark shape")
    if stale_fallback_resolutions != stale_expected * _RESOLUTION_REPETITIONS:
        raise RuntimeError("stale fallback count did not match the deterministic benchmark shape")

    return RuntimeBenchmarkResult(
        profile=profile,
        entity_count=entity_count,
        resolution_calls=resolution_calls,
        resolution_seconds=resolution_seconds,
        resolution_calls_per_second=resolution_calls / resolution_seconds if resolution_seconds else 0.0,
        fallback_resolutions=fallback_resolutions,
        stale_fallback_resolutions=stale_fallback_resolutions,
        retention_plan_seconds=retention_plan_seconds,
        retention_execute_seconds=retention_execute_seconds,
        selected_provider_contributions=plan.selected_provider_contributions,
        removed_provider_contributions=result.removed_provider_contributions,
        collected_entities=len(result.collected_entities),
        before_maintenance_bytes=(before.database_bytes or 0) + (before.wal_bytes or 0),
        after_maintenance_bytes=(after_maintenance.database_bytes or 0) + (after_maintenance.wal_bytes or 0),
        reusable_bytes_after_maintenance=after_maintenance.reusable_bytes,
        compaction_seconds=compaction_seconds,
        compaction_performed=compaction.vacuum_performed,
        after_compaction_bytes=compaction.after.database_bytes or 0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_ENTITY_COUNTS), default="normal")
    parser.add_argument("--entity-count", type=int, help="Override the profile's deterministic entity count.")
    parser.add_argument("--output", type=Path, help="Write JSON output to this path as well as stdout.")
    return parser


def main() -> int:
    args = _parser().parse_args()
    count = PROFILE_ENTITY_COUNTS[args.profile] if args.entity_count is None else args.entity_count
    if count <= 0:
        raise SystemExit("--entity-count must be positive")
    with tempfile.TemporaryDirectory(prefix="yt-discover-v4-runtime-benchmark-") as temporary:
        result = run_benchmark(Path(temporary) / "metadata.sqlite3", args.profile, count)
    payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
