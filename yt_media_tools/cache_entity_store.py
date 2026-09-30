"""Cache-v4 entity identity and provider-owned metadata storage."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Iterable, Mapping

from .cache_registry import ProviderDefinition, ProviderFieldDefinition
from .cache_registry_store import CacheV4RegistryStore, RegistryContractError


@dataclass(frozen=True)
class MediaEntity:
    """Stable cache-v4 identity for one service-owned media entity."""

    entity_id: int
    service: str
    external_id: str


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

    Acquisition state and observation semantics deliberately live in later #128
    layers. A stored NULL therefore has no standalone semantic meaning here.
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
