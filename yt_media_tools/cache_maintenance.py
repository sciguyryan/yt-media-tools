"""Planning primitives for cache-v4 retention and destructive maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sqlite3
from typing import Iterable

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
