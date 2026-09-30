"""Cache-v4 entity identity and provider metadata storage tests."""

from dataclasses import replace
import sqlite3

import pytest

from yt_media_tools.cache_entity_store import CacheV4EntityStore
from yt_media_tools.cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from yt_media_tools.cache_registry_store import CacheV4RegistryStore, RegistryContractError
from yt_media_tools.query_types import QueryType


def _field(name: str, kind: str, *, storage_name: str | None = None) -> ProviderFieldDefinition:
    return ProviderFieldDefinition(
        name=name,
        value_type=QueryType.scalar(kind),
        acquisition_group="basic-info",
        storage_name=storage_name or name,
        freshness=FreshnessPolicy.max_age(3600),
    )


def _provider(
    key: str = "ytdlp",
    *,
    revision: int = 1,
    fields: tuple[ProviderFieldDefinition, ...] | None = None,
) -> ProviderDefinition:
    return ProviderDefinition(
        key=key,
        schema_revision=revision,
        metadata_table=f"provider_{key}",
        acquisition_groups=(AcquisitionGroupDefinition("basic-info"),),
        fields=fields or (_field("duration", "duration"), _field("title", "string")),
        applicability=ProviderApplicability(services=frozenset({"youtube"})),
    )


def _stores(provider: ProviderDefinition) -> tuple[CacheV4RegistryStore, CacheV4EntityStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((provider,))
    entities = CacheV4EntityStore(connection, registry)
    entities.initialise((provider,))
    return registry, entities


def test_entity_identity_deduplicates_same_service_and_external_id() -> None:
    provider = _provider()
    _, store = _stores(provider)
    first = store.get_or_create_entity("youtube", "abc123")
    second = store.get_or_create_entity("youtube", "abc123")
    assert second == first
    assert store.entity("youtube", "abc123") == first


def test_same_external_id_on_different_services_is_a_distinct_entity() -> None:
    provider = _provider()
    _, store = _stores(provider)
    youtube = store.get_or_create_entity("youtube", "same-id")
    twitch = store.get_or_create_entity("twitch", "same-id")
    assert youtube.entity_id != twitch.entity_id


@pytest.mark.parametrize(
    ("service", "external_id"), [("", "id"), (" youtube", "id"), ("youtube", ""), ("youtube", "id ")]
)
def test_entity_identity_rejects_ambiguous_empty_or_padded_parts(service: str, external_id: str) -> None:
    provider = _provider()
    _, store = _stores(provider)
    with pytest.raises(ValueError):
        store.get_or_create_entity(service, external_id)


def test_provider_metadata_is_keyed_by_entity_not_source() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    store.write_provider_metadata(provider, entity.entity_id, {"duration": 42, "title": "Example"})
    assert store.provider_metadata(provider, entity.entity_id) == {
        "duration": 42,
        "title": "Example",
    }
    columns = {row["name"]: row["type"] for row in store.connection.execute('PRAGMA table_info("provider_ytdlp")')}
    assert columns == {"entity_id": "INTEGER", "duration": "INTEGER", "title": "TEXT"}


def test_provider_metadata_update_changes_only_named_fields() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    store.write_provider_metadata(provider, entity.entity_id, {"duration": 42, "title": "Before"})
    store.write_provider_metadata(provider, entity.entity_id, {"title": "After"})
    assert store.provider_metadata(provider, entity.entity_id) == {
        "duration": 42,
        "title": "After",
    }


def test_null_storage_does_not_create_acquisition_or_resolution_state() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    store.write_provider_metadata(provider, entity.entity_id, {"title": None})
    assert store.provider_metadata(provider, entity.entity_id)["title"] is None
    tables = {row[0] for row in store.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "cache_v4_acquisition_state" not in tables
    assert "cache_v4_field_observations" not in tables


def test_unknown_provider_field_is_rejected() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    with pytest.raises(ValueError, match="does not declare"):
        store.write_provider_metadata(provider, entity.entity_id, {"made_up": 1})


def test_new_scalar_field_adds_provider_column_without_rebuilding_existing_rows() -> None:
    provider = _provider(fields=(_field("duration", "duration"),))
    registry, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    store.write_provider_metadata(provider, entity.entity_id, {"duration": 42})

    evolved = replace(
        provider,
        schema_revision=2,
        fields=provider.fields + (_field("title", "string"),),
    )
    registry.reconcile((evolved,))
    store.initialise((evolved,))

    assert store.provider_metadata(evolved, entity.entity_id) == {
        "duration": 42,
        "title": None,
    }


def test_structured_field_requires_explicit_provider_storage_design() -> None:
    field = ProviderFieldDefinition(
        name="formats",
        value_type=QueryType.structured_opaque(),
        acquisition_group="basic-info",
        storage_name="formats",
        freshness=FreshnessPolicy.max_age(3600),
    )
    provider = _provider(fields=(field,))
    connection = sqlite3.connect(":memory:")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((provider,))
    store = CacheV4EntityStore(connection, registry)
    with pytest.raises(RegistryContractError, match="explicit structured storage"):
        store.initialise((provider,))


def test_provider_must_be_reconciled_before_metadata_storage() -> None:
    provider = _provider()
    connection = sqlite3.connect(":memory:")
    registry = CacheV4RegistryStore(connection)
    registry.initialise()
    store = CacheV4EntityStore(connection, registry)
    with pytest.raises(RegistryContractError, match="must be reconciled"):
        store.initialise((provider,))
