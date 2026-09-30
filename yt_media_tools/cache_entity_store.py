"""Cache-v4 entity identity and provider-owned metadata storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import sqlite3
from typing import Iterable, Mapping

from .cache_registry import FreshnessMode, FreshnessPolicy, ProviderDefinition, ProviderFieldDefinition
from .cache_registry_store import CacheV4RegistryStore, RegistryContractError


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
    if kind in {"boolean", "count", "duration", "integer"}:
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
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_v4_media_entities (
                entity_id INTEGER PRIMARY KEY,
                service TEXT NOT NULL,
                external_id TEXT NOT NULL,
                UNIQUE(service, external_id)
            )
            """
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_v4_acquisition_state (
                entity_id INTEGER NOT NULL REFERENCES cache_v4_media_entities(entity_id) ON DELETE CASCADE,
                provider_id INTEGER NOT NULL REFERENCES cache_v4_providers(provider_id),
                acquisition_group_id INTEGER NOT NULL REFERENCES cache_v4_acquisition_groups(acquisition_group_id),
                outcome TEXT NOT NULL CHECK (outcome IN ('success', 'failed')),
                last_attempt_at TEXT NOT NULL,
                last_success_at TEXT,
                failure_category TEXT,
                PRIMARY KEY(entity_id, provider_id, acquisition_group_id),
                CHECK (
                    (outcome = 'success' AND last_success_at = last_attempt_at AND failure_category IS NULL)
                    OR (
                        outcome = 'failed' AND failure_category IS NOT NULL
                        AND (last_success_at IS NULL OR last_success_at <= last_attempt_at)
                    )
                )
            )
            """
        )
        self.connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_insert
            BEFORE INSERT ON cache_v4_acquisition_state
            WHEN NOT EXISTS (
                SELECT 1 FROM cache_v4_acquisition_groups AS g
                WHERE g.acquisition_group_id = NEW.acquisition_group_id
                  AND g.provider_id = NEW.provider_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'acquisition group does not belong to provider');
            END;

            CREATE TRIGGER IF NOT EXISTS cache_v4_acquisition_state_provider_update
            BEFORE UPDATE OF provider_id, acquisition_group_id ON cache_v4_acquisition_state
            WHEN NOT EXISTS (
                SELECT 1 FROM cache_v4_acquisition_groups AS g
                WHERE g.acquisition_group_id = NEW.acquisition_group_id
                  AND g.provider_id = NEW.provider_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'acquisition group does not belong to provider');
            END;
            """
        )
        for provider in definitions:
            self._initialise_provider_table(provider)
        self.connection.commit()

    def _initialise_provider_table(self, provider: ProviderDefinition) -> None:
        row = self.connection.execute(
            """
            SELECT provider_id, metadata_table, declared
            FROM cache_v4_providers
            WHERE provider_key = ?
            """,
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

    def get_or_create_entity(self, service: str, external_id: str) -> MediaEntity:
        """Return the stable identity for one service/external-id pair."""
        service = _require_identity_part(service, label="service")
        external_id = _require_identity_part(external_id, label="external_id")
        self.connection.execute(
            """
            INSERT INTO cache_v4_media_entities(service, external_id)
            VALUES (?, ?)
            ON CONFLICT(service, external_id) DO NOTHING
            """,
            (service, external_id),
        )
        row = self.connection.execute(
            """
            SELECT entity_id, service, external_id
            FROM cache_v4_media_entities
            WHERE service = ? AND external_id = ?
            """,
            (service, external_id),
        ).fetchone()
        assert row is not None
        self.connection.commit()
        return MediaEntity(int(row["entity_id"]), str(row["service"]), str(row["external_id"]))

    def entity(self, service: str, external_id: str) -> MediaEntity | None:
        """Look up an existing entity without creating it."""
        service = _require_identity_part(service, label="service")
        external_id = _require_identity_part(external_id, label="external_id")
        row = self.connection.execute(
            """
            SELECT entity_id, service, external_id
            FROM cache_v4_media_entities
            WHERE service = ? AND external_id = ?
            """,
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
            """
            SELECT p.provider_id, g.acquisition_group_id
            FROM cache_v4_providers AS p
            JOIN cache_v4_acquisition_groups AS g ON g.provider_id = p.provider_id
            WHERE p.provider_key = ? AND p.declared = 1
              AND g.group_key = ? AND g.declared = 1
            """,
            (provider.key, group_key),
        ).fetchone()
        if row is None:
            raise RegistryContractError(
                f"Provider {provider.key!r} acquisition group {group_key!r} must be reconciled before state is recorded."
            )
        return int(row["provider_id"]), int(row["acquisition_group_id"])

    def _existing_attempt_time(self, entity_id: int, provider_id: int, acquisition_group_id: int) -> datetime | None:
        row = self.connection.execute(
            """
            SELECT last_attempt_at FROM cache_v4_acquisition_state
            WHERE entity_id = ? AND provider_id = ? AND acquisition_group_id = ?
            """,
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
    ) -> None:
        """Record a successful group resolution without assigning field winner semantics."""
        provider_id, group_id = self._acquisition_identity(provider, group_key)
        acquired_at = self._normalise_acquisition_time(acquired_at)
        previous = self._existing_attempt_time(entity_id, provider_id, group_id)
        if previous is not None and acquired_at < previous:
            raise ValueError("Acquisition attempts cannot be recorded earlier than the current latest attempt.")
        encoded = acquired_at.isoformat()
        self.connection.execute(
            """
            INSERT INTO cache_v4_acquisition_state(
                entity_id, provider_id, acquisition_group_id, outcome,
                last_attempt_at, last_success_at, failure_category
            ) VALUES (?, ?, ?, 'success', ?, ?, NULL)
            ON CONFLICT(entity_id, provider_id, acquisition_group_id) DO UPDATE SET
                outcome = 'success',
                last_attempt_at = excluded.last_attempt_at,
                last_success_at = excluded.last_success_at,
                failure_category = NULL
            """,
            (entity_id, provider_id, group_id, encoded, encoded),
        )
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
            """
            INSERT INTO cache_v4_acquisition_state(
                entity_id, provider_id, acquisition_group_id, outcome,
                last_attempt_at, last_success_at, failure_category
            ) VALUES (?, ?, ?, 'failed', ?, NULL, ?)
            ON CONFLICT(entity_id, provider_id, acquisition_group_id) DO UPDATE SET
                outcome = 'failed',
                last_attempt_at = excluded.last_attempt_at,
                failure_category = excluded.failure_category
            """,
            (entity_id, provider_id, group_id, encoded, category),
        )
        self.connection.commit()

    def _effective_field_freshness(
        self, provider: ProviderDefinition, field: ProviderFieldDefinition
    ) -> FreshnessPolicy:
        row = self.connection.execute(
            """
            SELECT f.default_freshness_mode, f.default_max_age_seconds,
                   f.freshness_mode_override, f.max_age_seconds_override
            FROM cache_v4_fields AS f
            JOIN cache_v4_providers AS p ON p.provider_id = f.provider_id
            WHERE p.provider_key = ? AND p.declared = 1
              AND f.field_name = ? AND f.declared = 1
            """,
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
            "SELECT service, external_id FROM cache_v4_media_entities WHERE entity_id = ?",
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
            """
            SELECT outcome, last_attempt_at, last_success_at, failure_category
            FROM cache_v4_acquisition_state
            WHERE entity_id = ? AND provider_id = ? AND acquisition_group_id = ?
            """,
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
