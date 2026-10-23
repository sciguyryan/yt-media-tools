"""Hardening tests for the completed cache-v4 registry contract."""

from dataclasses import replace
import sqlite3

import pytest

from yt_media_tools.cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from yt_media_tools.cache_registry_store import CacheV4RegistryStore, RegistryContractError
from yt_media_tools.query_types import QueryType


def _field(name: str, kind: str = "text") -> ProviderFieldDefinition:
    return ProviderFieldDefinition(
        name=name,
        value_type=QueryType.scalar(kind),
        acquisition_group="basic-info",
        storage_name=name.replace("-", "_"),
        freshness=FreshnessPolicy.max_age(3600),
    )


def _provider(
    key: str,
    *,
    revision: int = 1,
    fields: tuple[ProviderFieldDefinition, ...] = (_field("title"),),
) -> ProviderDefinition:
    return ProviderDefinition(
        key=key,
        schema_revision=revision,
        metadata_table=f"provider_{key}",
        acquisition_groups=(AcquisitionGroupDefinition("basic-info"),),
        fields=fields,
        applicability=ProviderApplicability(services=frozenset({"youtube"})),
    )


def test_removed_provider_retains_identity_but_is_not_currently_declared() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    youtubejs = _provider("youtubejs")
    ytdlp = _provider("ytdlp")
    store.reconcile((youtubejs, ytdlp))
    original = {p.key: p.provider_id for p in store.registered_providers()}
    store.reconcile((youtubejs,))
    assert store.declared_provider_keys() == ("youtubejs",)
    assert {p.key: p.provider_id for p in store.registered_providers()} == original
    assert (
        store.field_provider_candidates("title", available_provider_keys={"youtubejs", "ytdlp"})[0].provider_key
        == "youtubejs"
    )


def test_reinstalled_provider_recovers_original_identity_and_policy() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    youtubejs = _provider("youtubejs")
    store.reconcile((youtubejs,))
    original = store.registered_providers()[0]
    store.set_provider_policy("youtubejs", enabled=False, priority=41)
    store.reconcile(())
    store.reconcile((youtubejs,))
    restored = store.registered_providers()[0]
    assert restored.provider_id == original.provider_id
    assert restored.registration_order == original.registration_order
    assert restored.enabled is False
    assert restored.priority == 41


def test_removed_field_retains_identity_but_no_longer_claims_logical_field() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    title = _field("title")
    duration = _field("duration", "duration")
    provider = _provider("youtubejs", fields=(title, duration))
    store.reconcile((provider,))
    original = {
        row["field_name"]: row["field_id"]
        for row in store.connection.execute("SELECT field_id, field_name FROM cache_v4_fields")
    }
    store.reconcile((replace(provider, schema_revision=2, fields=(title,)),))
    assert store.field_provider_candidates("duration", available_provider_keys={"youtubejs"}) == ()
    stored = {
        row["field_name"]: (row["field_id"], row["declared"])
        for row in store.connection.execute("SELECT field_id, field_name, declared FROM cache_v4_fields")
    }
    assert stored["duration"] == (original["duration"], 0)


def test_readded_field_recovers_original_identity_and_registration_order() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    title = _field("title")
    duration = _field("duration", "duration")
    provider = _provider("youtubejs", fields=(title, duration))
    store.reconcile((provider,))
    before = store.connection.execute(
        "SELECT field_id, registration_order FROM cache_v4_fields WHERE field_name = 'duration'"
    ).fetchone()
    store.reconcile((replace(provider, schema_revision=2, fields=(title,)),))
    store.reconcile((replace(provider, schema_revision=3, fields=(title, duration)),))
    after = store.connection.execute(
        "SELECT field_id, registration_order, declared FROM cache_v4_fields WHERE field_name = 'duration'"
    ).fetchone()
    assert tuple(after) == (before["field_id"], before["registration_order"], 1)


def test_removed_shared_claim_no_longer_participates_in_compatibility() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    youtubejs = _provider("youtubejs", fields=(_field("title"),))
    ytdlp = _provider("ytdlp", fields=(_field("title"),))
    store.reconcile((youtubejs, ytdlp))
    ytdlp_without_title = replace(ytdlp, schema_revision=2, fields=())
    store.reconcile((youtubejs, ytdlp_without_title))
    other = _provider("ytmusicapi", fields=(_field("duration", "duration"),))
    store.reconcile((youtubejs, ytdlp_without_title, other))
    assert store.declared_provider_keys() == ("youtubejs", "ytdlp", "ytmusicapi")


def test_incompatible_new_shared_claim_rolls_back_declared_state_and_registration() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    youtubejs = _provider("youtubejs", fields=(_field("title"),))
    store.reconcile((youtubejs,))
    before = store.registered_providers()
    incompatible = _provider("ytdlp", fields=(_field("title", "integer"),))
    with pytest.raises(RegistryContractError, match="incompatible type claims"):
        store.reconcile((youtubejs, incompatible))
    assert store.registered_providers() == before
    assert store.declared_provider_keys() == ("youtubejs",)


def test_deterministic_reopen_preserves_historical_and_current_order() -> None:
    connection = sqlite3.connect(":memory:")
    store = CacheV4RegistryStore(connection)
    youtubejs = _provider("youtubejs")
    ytdlp = _provider("ytdlp")
    ytmusicapi = _provider("ytmusicapi")
    store.reconcile((youtubejs, ytdlp))
    store.reconcile((youtubejs,))
    store.reconcile((ytmusicapi, youtubejs))
    historical = [(p.key, p.registration_order) for p in store.registered_providers()]
    assert historical == [("youtubejs", 1), ("ytdlp", 2), ("ytmusicapi", 3)]
    assert store.declared_provider_keys() == ("youtubejs", "ytmusicapi")
    store.reconcile((youtubejs, ytmusicapi))
    assert [(p.key, p.registration_order) for p in store.registered_providers()] == historical
