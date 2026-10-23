"""Cache-v4 entity identity and provider-owned metadata storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import sqlite3
from typing import Iterable, Mapping

from .cache_registry import FreshnessMode, FreshnessPolicy, ProviderDefinition, ProviderFieldDefinition
from .cache_registry_store import CacheV4RegistryStore, RegistryContractError
from .sqlite.statements import load_statement


@dataclass(frozen=True)
class MediaEntity:
    """Stable cache-v4 identity for one service-owned media entity."""

    entity_id: int
    service: str
    external_id: str


class AcquisitionOutcome(str, Enum):
    """Outcome of the most recent acquisition attempt for one provider group."""

    SUCCESS = "success"
    FAILED = "failed"


class FieldObservationKind(str, Enum):
    """Derived state of one provider field for one cached entity."""

    VALUE = "value"
    KNOWN_NULL = "known-null"
    NOT_ACQUIRED = "not-acquired"
    UNSUPPORTED = "unsupported"
    INAPPLICABLE = "inapplicable"
    FAILED_ACQUISITION = "failed-acquisition"
    STALE = "stale"


@dataclass(frozen=True)
class FieldObservation:
    """Derived provider observation without selecting a cross-provider winner."""

    kind: FieldObservationKind
    value: object | None = None
    observed_at: datetime | None = None
    latest_attempt_failed: bool = False
    failure_category: str | None = None


@dataclass(frozen=True)
class ResolvedField:
    """Cross-provider resolution result for one logical scalar field."""

    field_name: str
    provider_key: str | None
    observation: FieldObservation | None

    @property
    def resolved(self) -> bool:
        """Whether resolution established a current value or known SQL NULL."""
        return self.observation is not None and self.observation.kind in {
            FieldObservationKind.VALUE,
            FieldObservationKind.KNOWN_NULL,
        }


@dataclass(frozen=True)
class SourceIdentity:
    """Stable cache-v4 identity for one logical source/facet boundary."""

    source_id: int
    source_url: str
    source_kind: str
    facet: str | None


@dataclass(frozen=True)
class SourceObservation:
    """Durable enumeration observation independent of provider metadata."""

    source: SourceIdentity
    last_observed_at: datetime
    observed_entries: int


@dataclass(frozen=True)
class AcquisitionGroupState:
    """Persistent acquisition history for one entity/provider/group boundary."""

    entity_id: int
    provider_id: int
    acquisition_group_id: int
    outcome: AcquisitionOutcome
    last_attempt_at: datetime
    last_success_at: datetime | None
    failure_category: str | None


def _require_identity_part(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a non-empty string with no surrounding whitespace.")
    return value


def _sqlite_type(field: ProviderFieldDefinition) -> str:
    """Return the lossless SQLite affinity used for one supported yt-sql scalar."""
    kind = field.value_type.kind
    if field.value_type.is_collection or field.value_type.is_structured:
        raise RegistryContractError(
            f"Provider field {field.name!r} requires explicit structured storage; "
            "cache-v4 does not serialise structured values into a scalar column."
        )
    if kind in {"boolean", "count", "datetime", "duration", "integer"}:
        return "INTEGER"
    if kind == "number":
        return "REAL"
    if kind in {"channel", "date", "playlist", "string", "text"}:
        return "TEXT"
    raise RegistryContractError(f"Provider field {field.name!r} has unsupported cache-v4 storage type {kind!r}.")


class CacheV4EntityStore:
    """Own entity identity and provider-owned scalar metadata tables.

    Provider metadata values and acquisition-group state share entity identity, but
    a stored NULL still has no standalone semantic meaning. Field observation and
    winner-resolution semantics remain later #128 layers.
    """

    def __init__(self, connection: sqlite3.Connection, registry: CacheV4RegistryStore):
        self.connection = connection
        self.registry = registry
        self.connection.row_factory = sqlite3.Row

    def initialise(self, definitions: Iterable[ProviderDefinition]) -> None:
        """Create entity identity and declared provider metadata tables."""
        definitions = tuple(definitions)
        self.connection.execute(load_statement("cache_v4/create_media_entities_table"))
        self.connection.executescript(load_statement("cache_v4/schema_source_state"))
        self.connection.execute(load_statement("cache_v4/create_acquisition_state_table"))
        self.connection.executescript(load_statement("cache_v4/schema_acquisition_triggers"))
        for provider in definitions:
            self._initialise_provider_table(provider)
        self.connection.commit()

    def _initialise_provider_table(self, provider: ProviderDefinition) -> None:
        row = self.connection.execute(
            load_statement("cache_v4/select_provider_registration"),
            (provider.key,),
        ).fetchone()
        if row is None or not bool(row["declared"]):
            raise RegistryContractError(
                f"Provider {provider.key!r} must be reconciled before metadata storage is initialised."
            )
        if row["metadata_table"] != provider.metadata_table:
            raise RegistryContractError(
                f"Provider {provider.key!r} metadata-table identity does not match the registry."
            )

        columns = ["entity_id INTEGER PRIMARY KEY REFERENCES cache_v4_media_entities(entity_id) ON DELETE CASCADE"]
        for field in provider.fields:
            columns.append(f'"{field.storage_name}" {_sqlite_type(field)}')
        sql = f'CREATE TABLE IF NOT EXISTS "{provider.metadata_table}" ({", ".join(columns)})'
        self.connection.execute(sql)

        actual = {
            str(item["name"]): str(item["type"]).upper()
            for item in self.connection.execute(f'PRAGMA table_info("{provider.metadata_table}")').fetchall()
        }
        if actual.get("entity_id") != "INTEGER":
            raise RegistryContractError(
                f"Provider {provider.key!r} metadata table has an incompatible entity_id column."
            )
        for field in provider.fields:
            sql_type = _sqlite_type(field)
            existing_type = actual.get(field.storage_name)
            if existing_type is None:
                self.connection.execute(
                    f'ALTER TABLE "{provider.metadata_table}" ADD COLUMN "{field.storage_name}" {sql_type}'
                )
            elif existing_type != sql_type:
                raise RegistryContractError(
                    f"Provider {provider.key!r} field {field.name!r} has SQLite type "
                    f"{existing_type!r}, expected {sql_type!r}."
                )

    def get_or_create_entity(self, service: str, external_id: str, *, commit: bool = True) -> MediaEntity:
        """Return the stable identity for one service/external-id pair."""
        service = _require_identity_part(service, label="service")
        external_id = _require_identity_part(external_id, label="external_id")
        self.connection.execute(
            load_statement("cache_v4/insert_entity"),
            (service, external_id),
        )
        row = self.connection.execute(
            load_statement("cache_v4/select_entity"),
            (service, external_id),
        ).fetchone()
        assert row is not None
        if commit:
            self.connection.commit()
        return MediaEntity(int(row["entity_id"]), str(row["service"]), str(row["external_id"]))

    def entity(self, service: str, external_id: str) -> MediaEntity | None:
        """Look up an existing entity without creating it."""
        service = _require_identity_part(service, label="service")
        external_id = _require_identity_part(external_id, label="external_id")
        row = self.connection.execute(
            load_statement("cache_v4/select_entity"),
            (service, external_id),
        ).fetchone()
        if row is None:
            return None
        return MediaEntity(int(row["entity_id"]), str(row["service"]), str(row["external_id"]))

    def write_provider_metadata(
        self,
        provider: ProviderDefinition,
        entity_id: int,
        values: Mapping[str, object | None],
        *,
        commit: bool = True,
    ) -> None:
        """Store declared provider scalar columns without assigning observation state."""
        fields = {field.name: field for field in provider.fields}
        unknown = sorted(set(values) - set(fields))
        if unknown:
            raise ValueError(f"Provider {provider.key!r} does not declare fields: {unknown!r}.")
        if not values:
            self.connection.execute(
                f'INSERT INTO "{provider.metadata_table}"(entity_id) VALUES (?) ON CONFLICT(entity_id) DO NOTHING',
                (entity_id,),
            )
            if commit:
                self.connection.commit()
            return
        storage = [(fields[name].storage_name, value) for name, value in values.items()]
        names = ["entity_id", *(name for name, _ in storage)]
        placeholders = ", ".join("?" for _ in names)
        assignments = ", ".join(f'"{name}" = excluded."{name}"' for name, _ in storage)
        quoted = ", ".join(f'"{name}"' for name in names)
        self.connection.execute(
            f'INSERT INTO "{provider.metadata_table}"({quoted}) VALUES ({placeholders}) '
            f"ON CONFLICT(entity_id) DO UPDATE SET {assignments}",
            (entity_id, *(value for _, value in storage)),
        )
        if commit:
            self.connection.commit()

    def provider_metadata(
        self,
        provider: ProviderDefinition,
        entity_id: int,
    ) -> dict[str, object | None] | None:
        """Return stored provider values by logical field name."""
        row = self.connection.execute(
            f'SELECT * FROM "{provider.metadata_table}" WHERE entity_id = ?',
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        return {field.name: row[field.storage_name] for field in provider.fields}

    @staticmethod
    def _normalise_acquisition_time(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Acquisition timestamps must be timezone-aware datetimes.")
        return value.astimezone(timezone.utc)

    def _acquisition_identity(self, provider: ProviderDefinition, group_key: str) -> tuple[int, int]:
        if group_key not in {group.key for group in provider.acquisition_groups}:
            raise ValueError(f"Provider {provider.key!r} does not declare acquisition group {group_key!r}.")
        row = self.connection.execute(
            load_statement("cache_v4/select_acquisition_group"),
            (provider.key, group_key),
        ).fetchone()
        if row is None:
            raise RegistryContractError(
                f"Provider {provider.key!r} acquisition group {group_key!r} must be reconciled before state is recorded."
            )
        return int(row["provider_id"]), int(row["acquisition_group_id"])

    def _existing_attempt_time(self, entity_id: int, provider_id: int, acquisition_group_id: int) -> datetime | None:
        row = self.connection.execute(
            load_statement("cache_v4/select_last_attempt"),
            (entity_id, provider_id, acquisition_group_id),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(str(row["last_attempt_at"])).astimezone(timezone.utc)

    def record_acquisition_success(
        self,
        provider: ProviderDefinition,
        entity_id: int,
        group_key: str,
        *,
        acquired_at: datetime,
        commit: bool = True,
    ) -> None:
        """Record a successful group resolution without assigning field winner semantics."""
        provider_id, group_id = self._acquisition_identity(provider, group_key)
        acquired_at = self._normalise_acquisition_time(acquired_at)
        previous = self._existing_attempt_time(entity_id, provider_id, group_id)
        if previous is not None and acquired_at < previous:
            raise ValueError("Acquisition attempts cannot be recorded earlier than the current latest attempt.")
        encoded = acquired_at.isoformat()
        self.connection.execute(
            load_statement("cache_v4/upsert_successful_acquisition"),
            (entity_id, provider_id, group_id, encoded, encoded),
        )
        if commit:
            self.connection.commit()

    def record_acquisition_failure(
        self,
        provider: ProviderDefinition,
        entity_id: int,
        group_key: str,
        *,
        attempted_at: datetime,
        category: str,
    ) -> None:
        """Record a recoverable failed attempt while preserving any prior success."""
        if not isinstance(category, str) or not category or category != category.strip():
            raise ValueError("Acquisition failure category must be a non-empty string with no surrounding whitespace.")
        provider_id, group_id = self._acquisition_identity(provider, group_key)
        attempted_at = self._normalise_acquisition_time(attempted_at)
        previous = self._existing_attempt_time(entity_id, provider_id, group_id)
        if previous is not None and attempted_at < previous:
            raise ValueError("Acquisition attempts cannot be recorded earlier than the current latest attempt.")
        encoded = attempted_at.isoformat()
        self.connection.execute(
            load_statement("cache_v4/upsert_failed_acquisition"),
            (entity_id, provider_id, group_id, encoded, category),
        )
        self.connection.commit()

    def _effective_field_freshness(
        self, provider: ProviderDefinition, field: ProviderFieldDefinition
    ) -> FreshnessPolicy:
        row = self.connection.execute(
            load_statement("cache_v4/select_field_freshness_by_provider"),
            (provider.key, field.name),
        ).fetchone()
        if row is None:
            raise RegistryContractError(
                f"Provider {provider.key!r} field {field.name!r} must be reconciled before observation state is read."
            )
        mode = (
            str(row["freshness_mode_override"])
            if row["freshness_mode_override"] is not None
            else str(row["default_freshness_mode"])
        )
        max_age = (
            row["max_age_seconds_override"]
            if row["freshness_mode_override"] is not None
            else row["default_max_age_seconds"]
        )
        return FreshnessPolicy(FreshnessMode(mode), max_age)

    @staticmethod
    def _observation_is_stale(observed_at: datetime, as_of: datetime, freshness: FreshnessPolicy) -> bool:
        if freshness.mode is FreshnessMode.IMMUTABLE:
            return False
        if freshness.mode is FreshnessMode.ALWAYS_REFRESH:
            return True
        assert freshness.max_age_seconds is not None
        return as_of > observed_at + timedelta(seconds=freshness.max_age_seconds)

    @staticmethod
    def _provider_is_inapplicable(
        provider: ProviderDefinition,
        entity: MediaEntity,
        *,
        source_kind: str | None,
        facet: str | None,
        source_traits: frozenset[str] | None,
    ) -> bool:
        applicability = provider.applicability
        if applicability.services is not None and entity.service not in applicability.services:
            return True
        if (
            source_kind is not None
            and applicability.source_kinds is not None
            and source_kind not in applicability.source_kinds
        ):
            return True
        if facet is not None and applicability.facets is not None and facet not in applicability.facets:
            return True
        return source_traits is not None and not applicability.required_source_traits.issubset(source_traits)

    def field_observation(
        self,
        provider: ProviderDefinition,
        entity_id: int,
        field_name: str,
        *,
        as_of: datetime,
        source_kind: str | None = None,
        facet: str | None = None,
        source_traits: frozenset[str] | None = None,
    ) -> FieldObservation:
        """Derive one provider field state without selecting a provider winner.

        Applicability dimensions are only used when the caller actually knows them.
        Missing source context is not evidence that a provider is inapplicable.
        """
        as_of = self._normalise_acquisition_time(as_of)
        field = provider.field(field_name)
        if field is None:
            return FieldObservation(FieldObservationKind.UNSUPPORTED)
        entity_row = self.connection.execute(
            load_statement("cache_v4/select_media_identity_by_entity_id"),
            (entity_id,),
        ).fetchone()
        if entity_row is None:
            raise ValueError(f"Unknown cache-v4 entity_id {entity_id!r}.")
        entity = MediaEntity(entity_id, str(entity_row["service"]), str(entity_row["external_id"]))
        if self._provider_is_inapplicable(
            provider,
            entity,
            source_kind=source_kind,
            facet=facet,
            source_traits=source_traits,
        ):
            return FieldObservation(FieldObservationKind.INAPPLICABLE)

        state = self.acquisition_state(provider, entity_id, field.acquisition_group)
        if state is None:
            return FieldObservation(FieldObservationKind.NOT_ACQUIRED)
        if state.last_success_at is None:
            return FieldObservation(
                FieldObservationKind.FAILED_ACQUISITION,
                latest_attempt_failed=True,
                failure_category=state.failure_category,
            )

        row = self.connection.execute(
            f'SELECT "{field.storage_name}" FROM "{provider.metadata_table}" WHERE entity_id = ?',
            (entity_id,),
        ).fetchone()
        if row is None:
            raise RegistryContractError(
                f"Provider {provider.key!r} has successful acquisition state for entity {entity_id} "
                f"but no metadata row for field {field.name!r}."
            )
        value = row[field.storage_name]
        failed = state.outcome is AcquisitionOutcome.FAILED
        failure_category = state.failure_category if failed else None
        freshness = self._effective_field_freshness(provider, field)
        if self._observation_is_stale(state.last_success_at, as_of, freshness):
            return FieldObservation(
                FieldObservationKind.STALE,
                value=value,
                observed_at=state.last_success_at,
                latest_attempt_failed=failed,
                failure_category=failure_category,
            )
        return FieldObservation(
            FieldObservationKind.KNOWN_NULL if value is None else FieldObservationKind.VALUE,
            value=value,
            observed_at=state.last_success_at,
            latest_attempt_failed=failed,
            failure_category=failure_category,
        )

    def get_or_create_source(self, source_url: str, source_kind: str, *, facet: str | None = None) -> SourceIdentity:
        """Return stable identity for one source/facet without implying observation trust."""
        source_url = _require_identity_part(source_url, label="source_url")
        source_kind = _require_identity_part(source_kind, label="source_kind")
        if facet is not None:
            facet = _require_identity_part(facet, label="facet")
        stored_facet = facet or ""
        self.connection.execute(
            load_statement("cache_v4/source_upsert"),
            (source_url, source_kind, stored_facet),
        )
        row = self.connection.execute(
            load_statement("cache_v4/source_by_url_facet"),
            (source_url, stored_facet),
        ).fetchone()
        assert row is not None
        self.connection.commit()
        return SourceIdentity(
            int(row["source_id"]),
            str(row["source_url"]),
            str(row["source_kind"]),
            str(row["facet"]) or None,
        )

    def record_source_observation(
        self, source: SourceIdentity, observed_entries: int, *, observed_at: datetime
    ) -> None:
        """Persist enumeration knowledge without creating coverage or frontier trust."""
        if observed_entries < 0:
            raise ValueError("observed_entries must be non-negative.")
        when = observed_at.astimezone(timezone.utc).isoformat()
        self.connection.execute(
            load_statement("cache_v4/source_observation_upsert"),
            (source.source_id, when, observed_entries),
        )
        self.connection.commit()

    def replace_source_entries(self, source: SourceIdentity, entity_ids: Iterable[int]) -> int:
        """Replace one trusted source/facet ordering using stable v4 entity identities."""
        ids = tuple(dict.fromkeys(entity_ids))
        with self.connection:
            self.connection.execute(load_statement("cache_v4/source_entries_delete"), (source.source_id,))
            self.connection.executemany(
                load_statement("cache_v4/source_entry_insert"),
                ((source.source_id, entity_id, index) for index, entity_id in enumerate(ids)),
            )
        return len(ids)

    def source_entry_ids(self, source: SourceIdentity) -> tuple[int, ...]:
        """Return the persisted newest-first entity ordering for one source/facet."""
        rows = self.connection.execute(
            load_statement("cache_v4/source_entry_ids"),
            (source.source_id,),
        ).fetchall()
        return tuple(int(row["entity_id"]) for row in rows)

    def source_observation(self, source: SourceIdentity) -> SourceObservation | None:
        """Return durable enumeration telemetry without inferring coverage/frontier state."""
        row = self.connection.execute(
            load_statement("cache_v4/source_observation_by_id"),
            (source.source_id,),
        ).fetchone()
        if row is None:
            return None
        return SourceObservation(
            source,
            datetime.fromisoformat(str(row["last_observed_at"])).astimezone(timezone.utc),
            int(row["observed_entries"]),
        )

    def record_source_coverage(
        self,
        source: SourceIdentity,
        observed_entries: int,
        cached_entries: int,
        *,
        complete: bool,
        reason: str,
        observed_at: datetime,
    ) -> None:
        """Persist an explicit coverage claim without promoting it to a frontier."""
        if observed_entries < 0 or cached_entries < 0:
            raise ValueError("Source coverage counts must be non-negative.")
        reason = _require_identity_part(reason, label="reason")
        when = self._normalise_acquisition_time(observed_at).isoformat()
        self.connection.execute(
            load_statement("cache_v4/source_coverage_upsert"),
            (source.source_id, when, observed_entries, cached_entries, int(complete), reason),
        )
        self.connection.commit()

    def record_source_frontier(
        self,
        source: SourceIdentity,
        head_entity_id: int,
        known_entries: int,
        *,
        overlap_confirmations: int,
        verified_at: datetime,
    ) -> None:
        """Persist a trusted frontier only when the caller has established one."""
        if known_entries < 0 or overlap_confirmations < 0:
            raise ValueError("Source frontier counts must be non-negative.")
        when = self._normalise_acquisition_time(verified_at).isoformat()
        self.connection.execute(
            load_statement("cache_v4/source_frontier_upsert"),
            (source.source_id, when, known_entries, head_entity_id, overlap_confirmations),
        )
        self.connection.commit()

    def _entity_has_provider_state(self, entity_id: int) -> bool:
        if (
            self.connection.execute(
                load_statement("cache_v4/exists_acquisition_for_entity"),
                (entity_id,),
            ).fetchone()
            is not None
        ):
            return True
        rows = self.connection.execute(load_statement("cache_v4/select_existing_provider_metadata_tables")).fetchall()
        for row in rows:
            table = str(row["metadata_table"]).replace('"', '""')
            if (
                self.connection.execute(
                    f'SELECT 1 FROM "{table}" WHERE entity_id = ? LIMIT 1',
                    (entity_id,),
                ).fetchone()
                is not None
            ):
                return True
        return False

    def _entity_has_source_state(self, entity_id: int) -> bool:
        if (
            self.connection.execute(
                load_statement("cache_v4/exists_source_entry_for_entity"),
                (entity_id,),
            ).fetchone()
            is not None
        ):
            return True
        return (
            self.connection.execute(
                load_statement("cache_v4/exists_frontier_with_head_entity"),
                (entity_id,),
            ).fetchone()
            is not None
        )

    def collect_entity_if_unreferenced(self, entity_id: int) -> bool:
        """Delete one entity only after provider and persistent source state release it."""
        if self._entity_has_provider_state(entity_id) or self._entity_has_source_state(entity_id):
            return False
        cursor = self.connection.execute(
            load_statement("cache_v4/delete_media_entity_by_id"),
            (entity_id,),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def prune_source_state(self, source: SourceIdentity) -> tuple[int, ...]:
        """Remove one source/facet boundary and dependent claims, then collect released entities."""
        entry_rows = self.connection.execute(
            load_statement("cache_v4/select_entity_ids_by_source_id"),
            (source.source_id,),
        ).fetchall()
        frontier = self.connection.execute(
            load_statement("cache_v4/select_frontier_head_entity_by_source_id"),
            (source.source_id,),
        ).fetchone()
        affected = {int(row["entity_id"]) for row in entry_rows}
        if frontier is not None:
            affected.add(int(frontier["head_entity_id"]))

        with self.connection:
            self.connection.execute(
                load_statement("cache_v4/delete_source_by_id"),
                (source.source_id,),
            )

        collected: list[int] = []
        for entity_id in sorted(affected):
            if self.collect_entity_if_unreferenced(entity_id):
                collected.append(entity_id)
        return tuple(collected)

    def import_legacy_source_state(
        self,
        *,
        service: str = "youtube",
        source_urls: Iterable[str] | None = None,
    ) -> int:
        """Import v3 source state without promoting observations into stronger claims.

        The bridge is intentionally idempotent. It preserves the legacy runtime during
        the wider cache migration while making v4 media identity authoritative for
        source membership and frontier heads.
        """
        service = _require_identity_part(service, label="service")
        table_names = {
            str(row["name"]) for row in self.connection.execute(load_statement("common/table_names")).fetchall()
        }
        required = {
            "source_observations",
            "source_entries",
            "source_coverage",
            "source_frontiers",
        }
        if not required.issubset(table_names):
            return 0

        selected = None if source_urls is None else tuple(dict.fromkeys(source_urls))
        if selected == ():
            return 0

        where = ""
        params: tuple[str, ...] = ()
        if selected is not None:
            placeholders = ", ".join("?" for _ in selected)
            where = f" WHERE source_url IN ({placeholders})"
            params = selected

        kinds: dict[str, str] = {}
        for table in ("source_observations", "source_coverage", "source_frontiers"):
            for row in self.connection.execute(
                f"SELECT source_url, source_kind FROM {table}{where}", params
            ).fetchall():
                kinds.setdefault(str(row["source_url"]), str(row["source_kind"]))

        urls = set(kinds)
        for row in self.connection.execute(f"SELECT DISTINCT source_url FROM source_entries{where}", params).fetchall():
            urls.add(str(row["source_url"]))

        imported = 0
        with self.connection:
            for source_url in sorted(urls):
                source_kind = kinds.get(source_url, "unknown")
                self.connection.execute(
                    load_statement("cache_v4/upsert_unfaceted_source"),
                    (source_url, source_kind),
                )
                source_id = int(
                    self.connection.execute(
                        load_statement("cache_v4/select_unfaceted_source_id"),
                        (source_url,),
                    ).fetchone()["source_id"]
                )

                observation = self.connection.execute(
                    load_statement("cache_v3/select_source_observation_by_url"),
                    (source_url,),
                ).fetchone()
                if observation is not None:
                    self.connection.execute(
                        load_statement("cache_v4/upsert_source_observation"),
                        (source_id, observation["last_observed_at"], observation["observed_entries"]),
                    )
                else:
                    self.connection.execute(
                        load_statement("cache_v4/delete_source_observation_by_source_id"),
                        (source_id,),
                    )

                entries = self.connection.execute(
                    load_statement("cache_v3/select_source_video_ids_in_order"),
                    (source_url,),
                ).fetchall()
                self.connection.execute(load_statement("cache_v4/source_entries_delete"), (source_id,))
                for index, row in enumerate(entries):
                    video_id = str(row["video_id"])
                    self.connection.execute(
                        load_statement("cache_v4/insert_entity"),
                        (service, video_id),
                    )
                    entity_id = int(
                        self.connection.execute(
                            load_statement("cache_v4/select_media_entity_id_by_identity"),
                            (service, video_id),
                        ).fetchone()["entity_id"]
                    )
                    self.connection.execute(
                        load_statement("cache_v4/source_entry_insert"),
                        (source_id, entity_id, index),
                    )

                coverage = self.connection.execute(
                    load_statement("cache_v3/select_source_coverage_by_url"),
                    (source_url,),
                ).fetchone()
                if coverage is None:
                    self.connection.execute(
                        load_statement("cache_v4/delete_source_coverage_by_source_id"), (source_id,)
                    )
                else:
                    self.connection.execute(
                        load_statement("cache_v4/source_coverage_upsert"),
                        (
                            source_id,
                            coverage["observed_at"],
                            coverage["observed_entries"],
                            coverage["cached_entries"],
                            coverage["complete"],
                            coverage["reason"],
                        ),
                    )

                frontier = self.connection.execute(
                    load_statement("cache_v3/select_source_frontier_by_url"),
                    (source_url,),
                ).fetchone()
                if frontier is None:
                    self.connection.execute(
                        load_statement("cache_v4/delete_source_frontier_by_source_id"), (source_id,)
                    )
                else:
                    head_id = str(frontier["head_video_id"])
                    self.connection.execute(
                        load_statement("cache_v4/insert_entity"),
                        (service, head_id),
                    )
                    head_entity_id = int(
                        self.connection.execute(
                            load_statement("cache_v4/select_media_entity_id_by_identity"),
                            (service, head_id),
                        ).fetchone()["entity_id"]
                    )
                    self.connection.execute(
                        load_statement("cache_v4/source_frontier_upsert"),
                        (
                            source_id,
                            frontier["verified_at"],
                            frontier["known_entries"],
                            head_entity_id,
                            frontier["overlap_confirmations"],
                        ),
                    )
                imported += 1
        return imported

    def resolve_field(
        self,
        providers: Iterable[ProviderDefinition],
        entity_id: int,
        field_name: str,
        *,
        as_of: datetime,
        source_kind: str | None = None,
        facet: str | None = None,
        source_traits: frozenset[str] | None = None,
    ) -> ResolvedField:
        """Resolve one logical scalar field across enabled available providers.

        Registry precedence orders candidates, but a fresh known NULL does not
        stop traversal because a lower-priority provider may still hold a fresh
        value. Stale observations remain diagnostic fallback state and are never
        promoted over a current value or known NULL.
        """
        definitions = {provider.key: provider for provider in providers}
        candidates = self.registry.field_provider_candidates(field_name, available_provider_keys=definitions)
        known_null: tuple[str, FieldObservation] | None = None
        stale: tuple[str, FieldObservation] | None = None
        for candidate in candidates:
            provider = definitions[candidate.provider_key]
            observation = self.field_observation(
                provider,
                entity_id,
                field_name,
                as_of=as_of,
                source_kind=source_kind,
                facet=facet,
                source_traits=source_traits,
            )
            if observation.kind is FieldObservationKind.VALUE:
                return ResolvedField(field_name, provider.key, observation)
            if observation.kind is FieldObservationKind.KNOWN_NULL and known_null is None:
                known_null = (provider.key, observation)
            elif observation.kind is FieldObservationKind.STALE and stale is None:
                stale = (provider.key, observation)

        if known_null is not None:
            provider_key, observation = known_null
            return ResolvedField(field_name, provider_key, observation)
        if stale is not None:
            provider_key, observation = stale
            return ResolvedField(field_name, provider_key, observation)
        return ResolvedField(field_name, None, None)

    def acquisition_state(
        self, provider: ProviderDefinition, entity_id: int, group_key: str
    ) -> AcquisitionGroupState | None:
        """Return persisted group state, or None when the group has never been acquired."""
        provider_id, group_id = self._acquisition_identity(provider, group_key)
        row = self.connection.execute(
            load_statement("cache_v4/select_acquisition_by_entity_provider_group"),
            (entity_id, provider_id, group_id),
        ).fetchone()
        if row is None:
            return None
        success = row["last_success_at"]
        return AcquisitionGroupState(
            entity_id=entity_id,
            provider_id=provider_id,
            acquisition_group_id=group_id,
            outcome=AcquisitionOutcome(str(row["outcome"])),
            last_attempt_at=datetime.fromisoformat(str(row["last_attempt_at"])).astimezone(timezone.utc),
            last_success_at=(
                datetime.fromisoformat(str(success)).astimezone(timezone.utc) if success is not None else None
            ),
            failure_category=(str(row["failure_category"]) if row["failure_category"] is not None else None),
        )
