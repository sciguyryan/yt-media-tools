"""Persistent cache-v4 registry reconciliation tests."""

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


def _provider(
    key: str = "youtubejs",
    *,
    schema_revision: int = 1,
    metadata_table: str | None = None,
    fields: tuple[ProviderFieldDefinition, ...] | None = None,
) -> ProviderDefinition:
    group = AcquisitionGroupDefinition("basic-info")
    return ProviderDefinition(
        key=key,
        schema_revision=schema_revision,
        metadata_table=metadata_table or f"provider_{key}",
        acquisition_groups=(group,),
        fields=fields
        or (
            ProviderFieldDefinition(
                name="duration",
                value_type=QueryType.scalar("duration"),
                acquisition_group=group.key,
                storage_name="duration",
                freshness=FreshnessPolicy.max_age(3600),
            ),
        ),
        applicability=ProviderApplicability(services=frozenset({"youtube"})),
    )


def _store() -> CacheV4RegistryStore:
    connection = sqlite3.connect(":memory:")
    return CacheV4RegistryStore(connection)


def test_reconcile_assigns_stable_provider_identity_and_registration_order() -> None:
    store = _store()
    store.reconcile((_provider("youtubejs"), _provider("ytdlp")))
    first = store.registered_providers()
    store.reconcile((_provider("ytdlp"), _provider("youtubejs")))
    assert store.registered_providers() == first
    assert [provider.key for provider in first] == ["youtubejs", "ytdlp"]
    assert [provider.registration_order for provider in first] == [1, 2]


def test_new_provider_appends_without_reassigning_existing_identity() -> None:
    store = _store()
    store.reconcile((_provider("youtubejs"),))
    first = store.registered_providers()[0]
    store.reconcile((_provider("youtubejs"), _provider("ytmusicapi")))
    providers = store.registered_providers()
    assert providers[0].provider_id == first.provider_id
    assert providers[0].registration_order == first.registration_order
    assert providers[1].registration_order == 2


def test_missing_implementation_does_not_delete_persistent_registration() -> None:
    store = _store()
    store.reconcile((_provider("youtubejs"), _provider("ytdlp")))
    store.reconcile((_provider("youtubejs"),))
    assert [provider.key for provider in store.registered_providers()] == ["youtubejs", "ytdlp"]


def test_database_owned_provider_policy_survives_reconciliation() -> None:
    store = _store()
    provider = _provider()
    store.reconcile((provider,))
    store.set_provider_policy(provider.key, enabled=False, priority=37)
    store.reconcile((provider,))
    registered = store.registered_providers()[0]
    assert registered.enabled is False
    assert registered.priority == 37


def test_field_overrides_survive_default_freshness_evolution() -> None:
    store = _store()
    provider = _provider()
    store.reconcile((provider,))
    store.set_field_overrides(
        provider.key,
        "duration",
        priority=9,
        freshness=FreshnessPolicy.immutable(),
    )
    changed_field = replace(provider.fields[0], freshness=FreshnessPolicy.max_age(7200))
    store.reconcile((replace(provider, schema_revision=2, fields=(changed_field,)),))
    row = store.connection.execute(
        """
        SELECT default_max_age_seconds, priority_override,
               freshness_mode_override, max_age_seconds_override
        FROM cache_v4_fields
        """
    ).fetchone()
    assert tuple(row) == (7200, 9, "immutable", None)


def test_provider_schema_revision_may_advance_but_not_go_backwards() -> None:
    store = _store()
    store.reconcile((_provider(schema_revision=1),))
    store.reconcile((_provider(schema_revision=2),))
    assert store.registered_providers()[0].schema_revision == 2
    with pytest.raises(RegistryContractError, match="newer than installed"):
        store.reconcile((_provider(schema_revision=1),))


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"metadata_table": "provider_other"}, "metadata_table"),
        (
            {
                "fields": (
                    ProviderFieldDefinition(
                        name="duration",
                        value_type=QueryType.scalar("integer"),
                        acquisition_group="basic-info",
                        storage_name="duration",
                        freshness=FreshnessPolicy.max_age(3600),
                    ),
                )
            },
            "type_json",
        ),
        (
            {
                "fields": (
                    ProviderFieldDefinition(
                        name="duration",
                        value_type=QueryType.scalar("duration"),
                        acquisition_group="basic-info",
                        storage_name="duration_seconds",
                        freshness=FreshnessPolicy.max_age(3600),
                    ),
                )
            },
            "storage_name",
        ),
    ],
)
def test_reconcile_rejects_incompatible_reuse_of_stable_identity(changed: dict[str, object], message: str) -> None:
    store = _store()
    provider = _provider()
    store.reconcile((provider,))
    with pytest.raises(RegistryContractError, match=message):
        store.reconcile((replace(provider, schema_revision=2, **changed),))


def test_fields_and_groups_append_without_reusing_registration_order() -> None:
    store = _store()
    provider = _provider()
    store.reconcile((provider,))
    added = ProviderFieldDefinition(
        name="title",
        value_type=QueryType.scalar("text"),
        acquisition_group="basic-info",
        storage_name="title",
        freshness=FreshnessPolicy.max_age(600),
    )
    store.reconcile((replace(provider, schema_revision=2, fields=provider.fields + (added,)),))
    rows = store.connection.execute(
        "SELECT field_name, registration_order FROM cache_v4_fields ORDER BY registration_order"
    ).fetchall()
    assert [tuple(row) for row in rows] == [("duration", 1), ("title", 2)]


def test_duplicate_provider_keys_are_rejected_before_reconciliation() -> None:
    store = _store()
    provider = _provider()
    with pytest.raises(ValueError, match="duplicate provider keys"):
        store.reconcile((provider, provider))
