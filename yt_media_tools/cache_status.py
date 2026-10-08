"""Read-only cache-v4 status and SQLite storage observations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
import sqlite3
from typing import Iterable

from .cache_maintenance import CacheRetentionPolicy, plan_cache_retention
from .cache_registry import FreshnessMode, FreshnessPolicy, ProviderDefinition
from .cache_registry_store import REGISTRY_SCHEMA_REVISION, CacheV4RegistryStore
from .freshness_config import FreshnessPolicyCatalogue, format_freshness_policy


@dataclass(frozen=True)
class ProviderCacheStatus:
    """Persistent and installed state for one cache provider."""

    key: str
    provider_id: int
    stored_schema_revision: int
    installed_schema_revision: int | None
    declared: bool
    enabled: bool
    priority: int
    metadata_records: int
    acquisition_records: int
    successful_acquisitions: int
    failed_acquisitions: int
    retention_eligible_contributions: int

    @property
    def available(self) -> bool:
        return self.declared and self.installed_schema_revision is not None

    @property
    def revision_current(self) -> bool:
        return self.installed_schema_revision == self.stored_schema_revision


@dataclass(frozen=True)
class SourceCacheStatus:
    """Summary of persisted source/facet state."""

    sources: int
    observations: int
    entries: int
    coverage_claims: int
    frontier_claims: int
    retention_eligible_sources: int


@dataclass(frozen=True)
class SQLiteCacheStatus:
    """Physical SQLite facts. These observations do not imply compaction policy."""

    journal_mode: str
    page_size: int
    page_count: int
    free_pages: int
    database_bytes: int | None
    wal_bytes: int | None
    shm_bytes: int | None

    @property
    def reusable_bytes(self) -> int:
        return self.page_size * self.free_pages


@dataclass(frozen=True)
class FreshnessCacheStatus:
    """One effective configured policy exposed for cache diagnostics."""

    provider: str
    field: str | None
    mode: str
    max_age_seconds: int | None
    origin: str


@dataclass(frozen=True)
class CacheStatus:
    """Structured cache status independent of terminal presentation."""

    cache_schema_version: int | None
    registry_schema_revision: int | None
    expected_registry_schema_revision: int
    entities: int
    providers: tuple[ProviderCacheStatus, ...]
    acquisition_records: int
    source: SourceCacheStatus
    retention: CacheRetentionPolicy
    freshness_policies: tuple[FreshnessCacheStatus, ...]
    sqlite: SQLiteCacheStatus

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["providers"] = [
            {**asdict(provider), "available": provider.available, "revision_current": provider.revision_current}
            for provider in self.providers
        ]
        payload["freshness_policies"] = [asdict(policy) for policy in self.freshness_policies]
        for key in ("provider_max_age", "source_max_age"):
            value = getattr(self.retention, key)
            payload["retention"][key] = None if value is None else int(value.total_seconds())
        return payload


def _count(connection: sqlite3.Connection, table: str) -> int:
    escaped = table.replace('"', '""')
    return int(connection.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0])


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def collect_cache_status(
    connection: sqlite3.Connection,
    path: Path,
    providers: Iterable[ProviderDefinition],
    *,
    retention: CacheRetentionPolicy | None = None,
    freshness: FreshnessPolicyCatalogue | None = None,
    now=None,
) -> CacheStatus:
    """Return a read-only status snapshot for an open cache database."""
    providers = tuple(providers)
    installed = {provider.key: provider for provider in providers}
    retention = retention or CacheRetentionPolicy()
    if retention.enabled and now is None:
        raise ValueError("now is required when reporting retention eligibility")
    plan = None if not retention.enabled else plan_cache_retention(connection, providers, retention, now=now)
    eligible = {}
    if plan is not None:
        for item in plan.provider_contributions:
            eligible[item.provider_key] = eligible.get(item.provider_key, 0) + 1

    schema_row = connection.execute("SELECT value FROM cache_meta WHERE key = 'schema_version'").fetchone()
    registry_row = connection.execute(
        "SELECT registry_schema_revision FROM cache_v4_registry_meta WHERE singleton = 1"
    ).fetchone()
    provider_rows = connection.execute(
        """
        SELECT provider_id, provider_key, schema_revision, metadata_table,
               declared, enabled, priority
        FROM cache_v4_providers
        ORDER BY registration_order
        """
    ).fetchall()
    provider_status = []
    for row in provider_rows:
        provider_id = int(row[0])
        key = str(row[1])
        definition = installed.get(key)
        acquisition = connection.execute(
            """
            SELECT COUNT(*),
                   SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN outcome = 'failed' THEN 1 ELSE 0 END)
            FROM cache_v4_acquisition_state WHERE provider_id = ?
            """,
            (provider_id,),
        ).fetchone()
        provider_status.append(
            ProviderCacheStatus(
                key=key,
                provider_id=provider_id,
                stored_schema_revision=int(row[2]),
                installed_schema_revision=None if definition is None else definition.schema_revision,
                declared=bool(row[4]),
                enabled=bool(row[5]),
                priority=int(row[6]),
                metadata_records=_count(connection, str(row[3])),
                acquisition_records=int(acquisition[0]),
                successful_acquisitions=int(acquisition[1] or 0),
                failed_acquisitions=int(acquisition[2] or 0),
                retention_eligible_contributions=eligible.get(key, 0),
            )
        )

    source_eligible = 0 if plan is None else plan.selected_source_states
    source = SourceCacheStatus(
        sources=_count(connection, "cache_v4_sources"),
        observations=_count(connection, "cache_v4_source_observations"),
        entries=_count(connection, "cache_v4_source_entries"),
        coverage_claims=_count(connection, "cache_v4_source_coverage"),
        frontier_claims=_count(connection, "cache_v4_source_frontiers"),
        retention_eligible_sources=source_eligible,
    )
    page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
    page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
    free_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
    path = path.expanduser()
    sqlite_status = SQLiteCacheStatus(
        journal_mode=journal_mode,
        page_size=page_size,
        page_count=page_count,
        free_pages=free_pages,
        database_bytes=_file_size(path),
        wal_bytes=_file_size(Path(str(path) + "-wal")),
        shm_bytes=_file_size(Path(str(path) + "-shm")),
    )
    freshness_status = []
    if freshness is not None:
        registry = CacheV4RegistryStore(connection)
        for provider in freshness.providers:
            overrides = dict(registry.field_freshness_overrides(provider.key))
            configured = ((None, provider.default), *provider.fields)
            for field, resolved in configured:
                if resolved is None:
                    continue
                policy = overrides.get(field, resolved.policy)
                origin = "database override" if field in overrides else resolved.origin
                freshness_status.append(
                    FreshnessCacheStatus(
                        provider=provider.key,
                        field=field,
                        mode=policy.mode.value,
                        max_age_seconds=policy.max_age_seconds,
                        origin=origin,
                    )
                )
    return CacheStatus(
        cache_schema_version=None if schema_row is None else int(schema_row[0]),
        registry_schema_revision=None if registry_row is None else int(registry_row[0]),
        expected_registry_schema_revision=REGISTRY_SCHEMA_REVISION,
        entities=_count(connection, "cache_v4_media_entities"),
        providers=tuple(provider_status),
        acquisition_records=_count(connection, "cache_v4_acquisition_state"),
        source=source,
        retention=retention,
        freshness_policies=tuple(freshness_status),
        sqlite=sqlite_status,
    )


def _age(value: timedelta | None) -> str:
    if value is None:
        return "disabled"
    seconds = int(value.total_seconds())
    if seconds % 86400 == 0:
        return f"{seconds // 86400}d"
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    return f"{seconds}s"


def format_cache_status(status: CacheStatus) -> str:
    """Render a compact human-readable status snapshot."""
    lines = [
        f"Cache schema: {status.cache_schema_version if status.cache_schema_version is not None else 'unknown'}",
        f"Registry schema: {status.registry_schema_revision if status.registry_schema_revision is not None else 'unknown'} (expected {status.expected_registry_schema_revision})",
        f"Entities: {status.entities}",
        f"Acquisition records: {status.acquisition_records}",
        "Providers:",
    ]
    if not status.providers:
        lines.append("  none")
    for provider in status.providers:
        state = []
        if not provider.available:
            state.append("unavailable")
        if not provider.enabled:
            state.append("disabled")
        if not provider.revision_current:
            state.append("revision mismatch")
        suffix = f" [{', '.join(state)}]" if state else ""
        lines.append(
            f"  {provider.key}: revision {provider.stored_schema_revision}, metadata {provider.metadata_records}, "
            f"acquisitions {provider.acquisition_records} ({provider.successful_acquisitions} successful, "
            f"{provider.failed_acquisitions} failed), retention-eligible {provider.retention_eligible_contributions}{suffix}"
        )
    lines.append("Freshness policies:")
    if not status.freshness_policies:
        lines.append("  unavailable")
    for configured in status.freshness_policies:
        field = configured.field if configured.field is not None else "default"
        policy = FreshnessPolicy(FreshnessMode(configured.mode), configured.max_age_seconds)
        lines.append(f"  {configured.provider}.{field}: {format_freshness_policy(policy)} ({configured.origin})")
    lines.extend(
        [
            (
                "Source state: "
                f"{status.source.sources} sources, {status.source.observations} observations, "
                f"{status.source.entries} entries, {status.source.coverage_claims} coverage claims, "
                f"{status.source.frontier_claims} frontier claims, "
                f"{status.source.retention_eligible_sources} retention-eligible"
            ),
            (
                "Retention: "
                f"provider {_age(status.retention.provider_max_age)}, source {_age(status.retention.source_max_age)}"
            ),
            (
                "SQLite: "
                f"journal={status.sqlite.journal_mode}, pages={status.sqlite.page_count}, free={status.sqlite.free_pages}, "
                f"page-size={status.sqlite.page_size}, reusable={status.sqlite.reusable_bytes} bytes, "
                f"database={status.sqlite.database_bytes if status.sqlite.database_bytes is not None else 'missing'} bytes, "
                f"WAL={status.sqlite.wal_bytes if status.sqlite.wal_bytes is not None else 0} bytes"
            ),
        ]
    )
    return "\n".join(lines)
