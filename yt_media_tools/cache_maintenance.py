"""Planning primitives for cache-v4 retention and destructive maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Callable, Iterable

from .cache_registry import ProviderDefinition


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("maintenance times must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class CacheRetentionPolicy:
    """Optional retention windows. None means that category is retained indefinitely."""

    provider_max_age: timedelta | None = None
    source_max_age: timedelta | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("provider_max_age", self.provider_max_age),
            ("source_max_age", self.source_max_age),
        ):
            if value is not None and value <= timedelta(0):
                raise ValueError(f"{name} must be positive when configured")

    @property
    def enabled(self) -> bool:
        return self.provider_max_age is not None or self.source_max_age is not None


@dataclass(frozen=True, order=True)
class ProviderContributionSelection:
    provider_key: str
    entity_id: int
    last_success_at: datetime


@dataclass(frozen=True, order=True)
class SourceStateSelection:
    source_id: int
    source_url: str
    facet: str
    last_observed_at: datetime


@dataclass(frozen=True)
class CacheMaintenancePlan:
    """Immutable selection result shared by preview and later execution."""

    planned_at: datetime
    policy: CacheRetentionPolicy
    provider_contributions: tuple[ProviderContributionSelection, ...] = ()
    source_states: tuple[SourceStateSelection, ...] = ()

    @property
    def selected_provider_contributions(self) -> int:
        return len(self.provider_contributions)

    @property
    def selected_source_states(self) -> int:
        return len(self.source_states)

    @property
    def selected_units(self) -> int:
        return self.selected_provider_contributions + self.selected_source_states

    @property
    def is_empty(self) -> bool:
        return self.selected_units == 0


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError("cache maintenance encountered a non-text timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError("cache maintenance encountered an invalid timestamp") from exc
    return _utc(parsed)


def plan_cache_retention(
    connection: sqlite3.Connection,
    providers: Iterable[ProviderDefinition],
    policy: CacheRetentionPolicy,
    *,
    now: datetime,
) -> CacheMaintenancePlan:
    """Select coherent retention units without mutating the database.

    Provider retention operates on one provider/entity contribution. Its age is
    determined by the most recent successful acquisition across that provider's
    acquisition groups. Source retention operates on the whole source/facet state
    using the source observation timestamp.
    """
    planned_at = _utc(now)
    providers = tuple(providers)
    provider_selections: list[ProviderContributionSelection] = []
    source_selections: list[SourceStateSelection] = []

    if policy.provider_max_age is not None:
        cutoff = planned_at - policy.provider_max_age
        for provider in providers:
            row = connection.execute(
                "SELECT provider_id, metadata_table, declared FROM cache_v4_providers WHERE provider_key = ?",
                (provider.key,),
            ).fetchone()
            if row is None:
                continue
            provider_id = int(row[0])
            metadata_table = str(row[1])
            entity_rows = connection.execute(
                f"""
                SELECT m.entity_id, MAX(a.last_success_at)
                FROM "{metadata_table}" AS m
                LEFT JOIN cache_v4_acquisition_state AS a
                  ON a.entity_id = m.entity_id
                 AND a.provider_id = ?
                 AND a.last_success_at IS NOT NULL
                GROUP BY m.entity_id
                """,
                (provider_id,),
            ).fetchall()
            for entity_id, last_success in entity_rows:
                if last_success is None:
                    continue
                successful_at = _parse_timestamp(last_success)
                if successful_at < cutoff:
                    provider_selections.append(
                        ProviderContributionSelection(provider.key, int(entity_id), successful_at)
                    )

    if policy.source_max_age is not None:
        cutoff = planned_at - policy.source_max_age
        rows = connection.execute(
            """
            SELECT s.source_id, s.source_url, s.facet, o.last_observed_at
            FROM cache_v4_sources AS s
            JOIN cache_v4_source_observations AS o ON o.source_id = s.source_id
            ORDER BY s.source_id
            """
        ).fetchall()
        for source_id, source_url, facet, last_observed in rows:
            observed_at = _parse_timestamp(last_observed)
            if observed_at < cutoff:
                source_selections.append(SourceStateSelection(int(source_id), str(source_url), str(facet), observed_at))

    return CacheMaintenancePlan(
        planned_at,
        policy,
        tuple(sorted(provider_selections)),
        tuple(sorted(source_selections)),
    )


class MaintenanceAuthorisationError(RuntimeError):
    """Raised when destructive maintenance has not been explicitly authorised."""


@dataclass(frozen=True)
class CacheMaintenanceAuthorisation:
    """Authorisation supplied by an explicit caller or configured automatic retention."""

    destructive: bool = False
    automatic_retention: bool = False

    @classmethod
    def explicit(cls) -> "CacheMaintenanceAuthorisation":
        return cls(destructive=True)

    @classmethod
    def configured_automatic_retention(cls) -> "CacheMaintenanceAuthorisation":
        return cls(destructive=True, automatic_retention=True)


@dataclass(frozen=True)
class CacheMaintenanceResult:
    """Observed outcome from executing one immutable maintenance plan."""

    planned_units: int
    removed_provider_contributions: int
    removed_source_states: int
    collected_entities: tuple[int, ...]

    @property
    def removed_units(self) -> int:
        return self.removed_provider_contributions + self.removed_source_states


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        is not None
    )


def _entity_is_unreferenced(connection: sqlite3.Connection, entity_id: int) -> bool:
    if (
        connection.execute(
            "SELECT 1 FROM cache_v4_acquisition_state WHERE entity_id = ? LIMIT 1", (entity_id,)
        ).fetchone()
        is not None
    ):
        return False
    if (
        connection.execute("SELECT 1 FROM cache_v4_source_entries WHERE entity_id = ? LIMIT 1", (entity_id,)).fetchone()
        is not None
    ):
        return False
    if (
        connection.execute(
            "SELECT 1 FROM cache_v4_source_frontiers WHERE head_entity_id = ? LIMIT 1", (entity_id,)
        ).fetchone()
        is not None
    ):
        return False
    for (table_name,) in connection.execute(
        """
        SELECT p.metadata_table
        FROM cache_v4_providers AS p
        JOIN sqlite_master AS m ON m.type = 'table' AND m.name = p.metadata_table
        """
    ).fetchall():
        escaped = str(table_name).replace('"', '""')
        if (
            connection.execute(f'SELECT 1 FROM "{escaped}" WHERE entity_id = ? LIMIT 1', (entity_id,)).fetchone()
            is not None
        ):
            return False
    return True


def execute_cache_maintenance(
    connection: sqlite3.Connection,
    providers: Iterable[ProviderDefinition],
    plan: CacheMaintenancePlan,
    *,
    authorisation: CacheMaintenanceAuthorisation,
) -> CacheMaintenanceResult:
    """Execute exactly one precomputed maintenance plan in one transaction.

    This function does not recalculate retention eligibility. Preview is the plan
    itself; execution consumes that same selection. Configured automatic retention
    uses the same executor and differs only in how authorisation is established.
    """
    if plan.is_empty:
        return CacheMaintenanceResult(0, 0, 0, ())
    if not authorisation.destructive:
        raise MaintenanceAuthorisationError(
            "destructive cache maintenance requires explicit or configured automatic authorisation"
        )

    definitions = {provider.key: provider for provider in providers}
    affected_entities: set[int] = set()
    removed_provider = 0
    removed_sources = 0

    try:
        connection.execute("BEGIN")
        for selected in plan.provider_contributions:
            provider = definitions.get(selected.provider_key)
            if provider is None:
                raise RuntimeError(f"maintenance plan references unknown provider {selected.provider_key!r}")
            row = connection.execute(
                "SELECT provider_id, metadata_table FROM cache_v4_providers WHERE provider_key = ?",
                (provider.key,),
            ).fetchone()
            if row is None:
                continue
            provider_id = int(row[0])
            metadata_table = str(row[1]).replace('"', '""')
            external = connection.execute(
                "SELECT external_id FROM cache_v4_media_entities WHERE entity_id = ?",
                (selected.entity_id,),
            ).fetchone()
            metadata_cursor = connection.execute(
                f'DELETE FROM "{metadata_table}" WHERE entity_id = ?', (selected.entity_id,)
            )
            acquisition_cursor = connection.execute(
                "DELETE FROM cache_v4_acquisition_state WHERE entity_id = ? AND provider_id = ?",
                (selected.entity_id, provider_id),
            )
            if metadata_cursor.rowcount or acquisition_cursor.rowcount:
                removed_provider += 1
                affected_entities.add(selected.entity_id)
            if (
                provider.key == "yt-dlp"
                and external is not None
                and _table_exists(connection, "cache_v4_raw_compatibility")
            ):
                connection.execute("DELETE FROM cache_v4_raw_compatibility WHERE video_id = ?", (str(external[0]),))

        for selected in plan.source_states:
            rows = connection.execute(
                "SELECT entity_id FROM cache_v4_source_entries WHERE source_id = ?",
                (selected.source_id,),
            ).fetchall()
            affected_entities.update(int(row[0]) for row in rows)
            frontier = connection.execute(
                "SELECT head_entity_id FROM cache_v4_source_frontiers WHERE source_id = ?",
                (selected.source_id,),
            ).fetchone()
            if frontier is not None:
                affected_entities.add(int(frontier[0]))
            cursor = connection.execute("DELETE FROM cache_v4_sources WHERE source_id = ?", (selected.source_id,))
            if cursor.rowcount:
                removed_sources += 1

        collected: list[int] = []
        for entity_id in sorted(affected_entities):
            if _entity_is_unreferenced(connection, entity_id):
                cursor = connection.execute("DELETE FROM cache_v4_media_entities WHERE entity_id = ?", (entity_id,))
                if cursor.rowcount:
                    collected.append(entity_id)
        connection.commit()
    except Exception:
        connection.rollback()
        raise

    return CacheMaintenanceResult(
        plan.selected_units,
        removed_provider,
        removed_sources,
        tuple(collected),
    )


def authorise_explicit_maintenance(
    plan: CacheMaintenancePlan,
    *,
    confirmation_threshold: int,
    interactive: bool,
    assume_yes: bool = False,
    confirm: Callable[[CacheMaintenancePlan], bool] | None = None,
) -> CacheMaintenanceAuthorisation:
    """Resolve explicit destructive authorisation without embedding a CLI threshold.

    The caller owns the configured threshold. Below it, an explicit maintenance
    request is sufficient. At or above it, non-interactive use requires explicit
    pre-authorisation; interactive use requires an affirmative confirmation.
    """
    if confirmation_threshold < 0:
        raise ValueError("confirmation_threshold must be non-negative")
    if plan.is_empty or plan.selected_units < confirmation_threshold:
        return CacheMaintenanceAuthorisation.explicit()
    if assume_yes:
        return CacheMaintenanceAuthorisation.explicit()
    if not interactive:
        raise MaintenanceAuthorisationError(
            "maintenance plan crosses the configured confirmation threshold; "
            "non-interactive execution requires explicit authorisation"
        )
    if confirm is None:
        raise ValueError("interactive maintenance requires a confirmation callback")
    if not bool(confirm(plan)):
        raise MaintenanceAuthorisationError("cache maintenance was not confirmed")
    return CacheMaintenanceAuthorisation.explicit()


def run_configured_retention(
    connection: sqlite3.Connection,
    providers: Iterable[ProviderDefinition],
    policy: CacheRetentionPolicy,
    *,
    now: datetime,
) -> tuple[CacheMaintenancePlan, CacheMaintenanceResult]:
    """Plan and execute configured automatic retention through the shared machinery."""
    plan = plan_cache_retention(connection, providers, policy, now=now)
    result = execute_cache_maintenance(
        connection,
        providers,
        plan,
        authorisation=CacheMaintenanceAuthorisation.configured_automatic_retention(),
    )
    return plan, result
