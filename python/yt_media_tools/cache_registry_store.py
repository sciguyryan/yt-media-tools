"""Persistent cache-v4 provider registry and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Iterable

from .cache_registry import (
    FreshnessMode,
    FreshnessPolicy,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from .query_types import CollectionOrdering, QueryType, StructuredMember, StructuredShape
from .sqlite.statements import load_statement

REGISTRY_SCHEMA_REVISION = 1


class RegistryContractError(RuntimeError):
    """A persisted stable identity conflicts with the installed code contract."""


@dataclass(frozen=True)
class RegisteredProvider:
    """Persistent identity and deployment policy for one provider."""

    provider_id: int
    key: str
    registration_order: int
    enabled: bool
    priority: int
    schema_revision: int


@dataclass(frozen=True)
class FieldProviderCandidate:
    """Registry metadata for one provider that can supply a logical field."""

    provider_id: int
    provider_key: str
    provider_registration_order: int
    field_id: int
    field_name: str
    field_type: QueryType
    acquisition_group_id: int
    acquisition_group: str
    effective_priority: int
    freshness: FreshnessPolicy


def _type_payload(value_type: QueryType) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": value_type.kind,
        "nullable": value_type.nullable,
    }
    if value_type.is_collection:
        assert value_type.element_type is not None
        assert value_type.ordering is not None
        payload["element_type"] = _type_payload(value_type.element_type)
        payload["ordering"] = value_type.ordering.value
    elif value_type.is_structured:
        assert value_type.structured_shape is not None
        payload["structured_shape"] = value_type.structured_shape.value
        payload["members"] = [
            {"name": member.name, "value_type": _type_payload(member.value_type)} for member in value_type.members
        ]
    return payload


def _type_from_payload(payload: dict[str, object]) -> QueryType:
    kind = str(payload["kind"])
    nullable = bool(payload["nullable"])
    if kind == "collection":
        element = payload.get("element_type")
        if not isinstance(element, dict):
            raise RegistryContractError("Stored collection type has no element_type object.")
        return QueryType.collection(
            _type_from_payload(element),
            nullable=nullable,
            ordering=CollectionOrdering(str(payload["ordering"])),
        )
    if kind == "structured":
        shape = StructuredShape(str(payload["structured_shape"]))
        if shape is StructuredShape.OPAQUE:
            return QueryType.structured_opaque(nullable=nullable)
        members_payload = payload.get("members", [])
        if not isinstance(members_payload, list):
            raise RegistryContractError("Stored structured type has invalid members.")
        members = []
        for member in members_payload:
            if not isinstance(member, dict) or not isinstance(member.get("value_type"), dict):
                raise RegistryContractError("Stored structured member is invalid.")
            members.append(
                StructuredMember(
                    str(member["name"]),
                    _type_from_payload(member["value_type"]),
                )
            )
        return QueryType.structured(members, nullable=nullable, shape=shape)
    return QueryType.scalar(kind, nullable=nullable)


def _type_json(value_type: QueryType) -> str:
    return json.dumps(_type_payload(value_type), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _applicability_json(provider: ProviderDefinition) -> str:
    applicability = provider.applicability
    payload = {
        "services": sorted(applicability.services) if applicability.services is not None else None,
        "source_kinds": sorted(applicability.source_kinds) if applicability.source_kinds is not None else None,
        "facets": sorted(applicability.facets) if applicability.facets is not None else None,
        "required_source_traits": sorted(applicability.required_source_traits),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _freshness_columns(policy: FreshnessPolicy) -> tuple[str, int | None]:
    return policy.mode.value, policy.max_age_seconds


class CacheV4RegistryStore:
    """Own the persistent half of the cache-v4 provider registry.

    Code declarations describe installed provider semantics. SQLite owns stable
    identities, append-only registration order and deployment policy.
    """

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.connection.row_factory = sqlite3.Row

    def initialise(self) -> None:
        """Create the registry tables without activating cache-v4 runtime use."""
        self.connection.executescript(load_statement("cache_v4/registry_schema"))
        row = self.connection.execute(load_statement("cache_v4/registry_revision")).fetchone()
        if row is None:
            self.connection.execute(
                load_statement("cache_v4/registry_insert_revision"),
                (REGISTRY_SCHEMA_REVISION,),
            )
        elif row["registry_schema_revision"] != REGISTRY_SCHEMA_REVISION:
            raise RegistryContractError(
                f"Unsupported cache-v4 registry schema revision {row['registry_schema_revision']!r}."
            )
        self.connection.commit()

    def reconcile(self, definitions: Iterable[ProviderDefinition]) -> None:
        """Reconcile installed declarations without rewriting persistent policy."""
        definitions = tuple(definitions)
        keys = [provider.key for provider in definitions]
        if len(keys) != len(set(keys)):
            raise ValueError("Provider registry reconciliation received duplicate provider keys.")

        self.initialise()
        try:
            self.connection.execute("BEGIN")
            self.connection.execute(load_statement("cache_v4/registry_reset_providers"))
            self.connection.execute(load_statement("cache_v4/registry_reset_groups"))
            self.connection.execute(load_statement("cache_v4/registry_reset_fields"))
            for provider in definitions:
                self._reconcile_provider(provider)
            self._validate_shared_field_contracts()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def _reconcile_provider(self, provider: ProviderDefinition) -> None:
        row = self.connection.execute(
            load_statement("cache_v4/registry_find_provider"),
            (provider.key,),
        ).fetchone()
        applicability_json = _applicability_json(provider)
        if row is None:
            next_order = self.connection.execute(
                load_statement("cache_v4/registry_next_provider_registration_order")
            ).fetchone()[0]
            cursor = self.connection.execute(
                load_statement("cache_v4/registry_insert_provider"),
                (
                    provider.key,
                    next_order,
                    provider.schema_revision,
                    provider.metadata_table,
                    applicability_json,
                ),
            )
            provider_id = int(cursor.lastrowid)
        else:
            provider_id = int(row["provider_id"])
            self.connection.execute(
                load_statement("cache_v4/registry_mark_provider_declared"),
                (provider_id,),
            )
            if row["metadata_table"] != provider.metadata_table:
                raise RegistryContractError(
                    f"Provider {provider.key!r} changed metadata_table from "
                    f"{row['metadata_table']!r} to {provider.metadata_table!r}."
                )
            if int(row["schema_revision"]) > provider.schema_revision:
                raise RegistryContractError(
                    f"Provider {provider.key!r} database schema revision "
                    f"{row['schema_revision']} is newer than installed revision "
                    f"{provider.schema_revision}."
                )
            if row["applicability_json"] != applicability_json:
                raise RegistryContractError(f"Provider {provider.key!r} changed its persisted applicability contract.")
            if int(row["schema_revision"]) < provider.schema_revision:
                self.connection.execute(
                    load_statement("cache_v4/registry_update_provider_schema_revision"),
                    (provider.schema_revision, provider_id),
                )

        group_ids: dict[str, int] = {}
        for group in provider.acquisition_groups:
            existing = self.connection.execute(
                load_statement("cache_v4/registry_acquisition_group_id_by_key"),
                (provider_id, group.key),
            ).fetchone()
            if existing is None:
                next_order = self.connection.execute(
                    load_statement("cache_v4/registry_next_acquisition_group_registration_order"),
                    (provider_id,),
                ).fetchone()[0]
                cursor = self.connection.execute(
                    load_statement("cache_v4/registry_insert_acquisition_group"),
                    (provider_id, group.key, next_order),
                )
                group_ids[group.key] = int(cursor.lastrowid)
            else:
                group_ids[group.key] = int(existing["acquisition_group_id"])
                self.connection.execute(
                    load_statement("cache_v4/registry_mark_acquisition_group_declared"),
                    (group_ids[group.key],),
                )

        for field in provider.fields:
            self._reconcile_field(provider_id, provider.key, field, group_ids[field.acquisition_group])

    def _reconcile_field(
        self,
        provider_id: int,
        provider_key: str,
        field: ProviderFieldDefinition,
        acquisition_group_id: int,
    ) -> None:
        row = self.connection.execute(
            load_statement("cache_v4/registry_find_field"),
            (provider_id, field.name),
        ).fetchone()
        type_json = _type_json(field.value_type)
        freshness_mode, max_age = _freshness_columns(field.freshness)
        if row is None:
            next_order = self.connection.execute(
                load_statement("cache_v4/registry_next_field_registration_order"),
                (provider_id,),
            ).fetchone()[0]
            self.connection.execute(
                load_statement("cache_v4/registry_insert_field"),
                (
                    provider_id,
                    field.name,
                    field.storage_name,
                    acquisition_group_id,
                    next_order,
                    type_json,
                    freshness_mode,
                    max_age,
                ),
            )
            return

        self.connection.execute(
            load_statement("cache_v4/registry_mark_field_declared"),
            (row["field_id"],),
        )
        expected = {
            "storage_name": field.storage_name,
            "acquisition_group_id": acquisition_group_id,
            "type_json": type_json,
        }
        for column, value in expected.items():
            if row[column] != value:
                raise RegistryContractError(
                    f"Provider {provider_key!r} field {field.name!r} changed stable "
                    f"{column} from {row[column]!r} to {value!r}."
                )
        if row["default_freshness_mode"] != freshness_mode or row["default_max_age_seconds"] != max_age:
            self.connection.execute(
                load_statement("cache_v4/registry_update_field_default_freshness"),
                (freshness_mode, max_age, row["field_id"]),
            )

    def _validate_shared_field_contracts(self) -> None:
        """Require every shared logical-field claim to use one yt-sql type."""
        rows = self.connection.execute(load_statement("cache_v4/registry_shared_field_type_claims")).fetchall()
        by_field: dict[str, tuple[str, str]] = {}
        for row in rows:
            field_name = str(row["field_name"])
            type_json = str(row["type_json"])
            existing = by_field.get(field_name)
            if existing is None:
                by_field[field_name] = (type_json, str(row["provider_key"]))
                continue
            existing_type, existing_provider = existing
            if type_json != existing_type:
                raise RegistryContractError(
                    f"Logical field {field_name!r} has incompatible type claims from "
                    f"providers {existing_provider!r} and {row['provider_key']!r}."
                )

    @staticmethod
    def _freshness_from_columns(mode: str, max_age_seconds: int | None) -> FreshnessPolicy:
        freshness_mode = FreshnessMode(mode)
        return FreshnessPolicy(freshness_mode, max_age_seconds)

    def field_provider_candidates(
        self,
        field_name: str,
        *,
        available_provider_keys: Iterable[str],
    ) -> tuple[FieldProviderCandidate, ...]:
        """Return enabled, installed providers for a field in precedence order.

        This is registry planning metadata only. It does not inspect entity values,
        acquisition state or observation freshness and therefore cannot select the
        winning cached value for an entity.
        """
        available = frozenset(available_provider_keys)
        rows = self.connection.execute(
            load_statement("cache_v4/registry_field_provider_candidates"),
            (field_name,),
        ).fetchall()

        candidates = []
        for row in rows:
            provider_key = str(row["provider_key"])
            if not bool(row["enabled"]) or provider_key not in available:
                continue
            effective_priority = (
                int(row["priority_override"]) if row["priority_override"] is not None else int(row["provider_priority"])
            )
            freshness_mode = (
                str(row["freshness_mode_override"])
                if row["freshness_mode_override"] is not None
                else str(row["default_freshness_mode"])
            )
            max_age_seconds = (
                row["max_age_seconds_override"]
                if row["freshness_mode_override"] is not None
                else row["default_max_age_seconds"]
            )
            candidates.append(
                FieldProviderCandidate(
                    provider_id=int(row["provider_id"]),
                    provider_key=provider_key,
                    provider_registration_order=int(row["provider_registration_order"]),
                    field_id=int(row["field_id"]),
                    field_name=str(row["field_name"]),
                    field_type=_type_from_payload(json.loads(str(row["type_json"]))),
                    acquisition_group_id=int(row["acquisition_group_id"]),
                    acquisition_group=str(row["group_key"]),
                    effective_priority=effective_priority,
                    freshness=self._freshness_from_columns(freshness_mode, max_age_seconds),
                )
            )
        candidates.sort(
            key=lambda candidate: (
                -candidate.effective_priority,
                candidate.provider_registration_order,
            )
        )
        return tuple(candidates)

    def registered_providers(self) -> tuple[RegisteredProvider, ...]:
        rows = self.connection.execute(load_statement("cache_v4/registry_registered_providers")).fetchall()
        return tuple(
            RegisteredProvider(
                provider_id=int(row["provider_id"]),
                key=str(row["provider_key"]),
                registration_order=int(row["registration_order"]),
                enabled=bool(row["enabled"]),
                priority=int(row["priority"]),
                schema_revision=int(row["schema_revision"]),
            )
            for row in rows
        )

    def declared_provider_keys(self) -> tuple[str, ...]:
        """Return provider keys declared by the current installed registry contract."""
        rows = self.connection.execute(load_statement("cache_v4/registry_declared_provider_keys")).fetchall()
        return tuple(str(row["provider_key"]) for row in rows)

    def field_freshness_overrides(self, provider_key: str) -> tuple[tuple[str, FreshnessPolicy], ...]:
        """Return explicit database-owned freshness overrides for one provider."""
        rows = self.connection.execute(
            load_statement("cache_v4/registry_field_freshness_overrides"),
            (provider_key,),
        ).fetchall()
        return tuple(
            (
                str(row["field_name"]),
                self._freshness_from_columns(
                    str(row["freshness_mode_override"]),
                    row["max_age_seconds_override"],
                ),
            )
            for row in rows
        )

    def set_provider_policy(
        self,
        provider_key: str,
        *,
        enabled: bool | None = None,
        priority: int | None = None,
    ) -> None:
        """Change database-owned provider policy without changing its contract."""
        row = self.connection.execute(
            load_statement("cache_v4/registry_provider_id_by_key"),
            (provider_key,),
        ).fetchone()
        if row is None:
            raise KeyError(provider_key)
        if enabled is not None:
            self.connection.execute(
                load_statement("cache_v4/registry_set_provider_enabled"),
                (int(enabled), row["provider_id"]),
            )
        if priority is not None:
            self.connection.execute(
                load_statement("cache_v4/registry_set_provider_priority"),
                (priority, row["provider_id"]),
            )
        self.connection.commit()

    def set_field_overrides(
        self,
        provider_key: str,
        field_name: str,
        *,
        priority: int | None = None,
        freshness: FreshnessPolicy | None = None,
        clear_priority: bool = False,
        clear_freshness: bool = False,
    ) -> None:
        """Set or clear database-owned per-field precedence/freshness overrides."""
        row = self.connection.execute(
            load_statement("cache_v4/registry_field_id_by_provider_and_name"),
            (provider_key, field_name),
        ).fetchone()
        if row is None:
            raise KeyError((provider_key, field_name))
        field_id = row["field_id"]
        if clear_priority:
            self.connection.execute(
                load_statement("cache_v4/registry_clear_field_priority"),
                (field_id,),
            )
        elif priority is not None:
            self.connection.execute(
                load_statement("cache_v4/registry_set_field_priority"),
                (priority, field_id),
            )
        if clear_freshness:
            self.connection.execute(
                load_statement("cache_v4/registry_clear_field_freshness"),
                (field_id,),
            )
        elif freshness is not None:
            mode, max_age = _freshness_columns(freshness)
            self.connection.execute(
                load_statement("cache_v4/registry_set_field_freshness"),
                (mode, max_age, field_id),
            )
        self.connection.commit()
