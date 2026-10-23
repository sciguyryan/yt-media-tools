"""Cache-v4 registry field-provider resolution metadata tests."""

import sqlite3

import pytest

from yt_media_tools.cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessMode,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from yt_media_tools.cache_registry_store import CacheV4RegistryStore, RegistryContractError
from yt_media_tools.query_types import QueryType


def _provider(
    key: str,
    *,
    field_type: QueryType | None = None,
    freshness: FreshnessPolicy | None = None,
) -> ProviderDefinition:
    group = AcquisitionGroupDefinition("basic-info")
    return ProviderDefinition(
        key=key,
        schema_revision=1,
        metadata_table=f"provider_{key}",
        acquisition_groups=(group,),
        fields=(
            ProviderFieldDefinition(
                name="duration",
                value_type=field_type or QueryType.scalar("duration"),
                acquisition_group=group.key,
                storage_name="duration",
                freshness=freshness or FreshnessPolicy.max_age(3600),
            ),
        ),
        applicability=ProviderApplicability(services=frozenset({"youtube"})),
    )


def _store(*providers: ProviderDefinition) -> CacheV4RegistryStore:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    store.reconcile(providers)
    return store


def test_candidates_use_provider_priority_then_persistent_registration_order() -> None:
    store = _store(_provider("youtubejs"), _provider("ytdlp"), _provider("ytmusicapi"))
    store.set_provider_policy("youtubejs", priority=10)
    store.set_provider_policy("ytdlp", priority=20)
    store.set_provider_policy("ytmusicapi", priority=20)
    candidates = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp", "ytmusicapi"},
    )
    assert [candidate.provider_key for candidate in candidates] == [
        "ytdlp",
        "ytmusicapi",
        "youtubejs",
    ]


def test_field_priority_override_replaces_provider_priority() -> None:
    store = _store(_provider("youtubejs"), _provider("ytdlp"))
    store.set_provider_policy("youtubejs", priority=100)
    store.set_provider_policy("ytdlp", priority=10)
    store.set_field_overrides("ytdlp", "duration", priority=200)
    candidates = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp"},
    )
    assert [(candidate.provider_key, candidate.effective_priority) for candidate in candidates] == [
        ("ytdlp", 200),
        ("youtubejs", 100),
    ]


def test_disabled_and_unavailable_providers_are_not_candidates() -> None:
    store = _store(_provider("youtubejs"), _provider("ytdlp"), _provider("ytmusicapi"))
    store.set_provider_policy("ytdlp", enabled=False)
    candidates = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp"},
    )
    assert [candidate.provider_key for candidate in candidates] == ["youtubejs"]
    assert {provider.key for provider in store.registered_providers()} == {
        "youtubejs",
        "ytdlp",
        "ytmusicapi",
    }


def test_candidate_exposes_acquisition_group_type_and_effective_freshness() -> None:
    store = _store(_provider("youtubejs"))
    store.set_field_overrides(
        "youtubejs",
        "duration",
        freshness=FreshnessPolicy.immutable(),
    )
    candidate = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs"},
    )[0]
    assert candidate.acquisition_group == "basic-info"
    assert candidate.field_type == QueryType.scalar("duration")
    assert candidate.freshness.mode is FreshnessMode.IMMUTABLE
    assert candidate.freshness.max_age_seconds is None


def test_default_freshness_is_used_without_override() -> None:
    store = _store(_provider("youtubejs", freshness=FreshnessPolicy.max_age(7200)))
    candidate = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs"},
    )[0]
    assert candidate.freshness == FreshnessPolicy.max_age(7200)


def test_shared_field_claims_require_compatible_yt_sql_types() -> None:
    store = CacheV4RegistryStore(sqlite3.connect(":memory:"))
    with pytest.raises(RegistryContractError, match="incompatible type claims"):
        store.reconcile(
            (
                _provider("youtubejs", field_type=QueryType.scalar("duration")),
                _provider("ytdlp", field_type=QueryType.scalar("integer")),
            )
        )
    assert store.registered_providers() == ()


def test_compatible_shared_field_claims_reconcile_normally() -> None:
    store = _store(_provider("youtubejs"), _provider("ytdlp"))
    candidates = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp"},
    )
    assert [candidate.provider_key for candidate in candidates] == ["youtubejs", "ytdlp"]


def test_candidate_order_is_stable_across_reopen_order() -> None:
    connection = sqlite3.connect(":memory:")
    store = CacheV4RegistryStore(connection)
    youtubejs = _provider("youtubejs")
    ytdlp = _provider("ytdlp")
    store.reconcile((youtubejs, ytdlp))
    first = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp"},
    )
    store.reconcile((ytdlp, youtubejs))
    second = store.field_provider_candidates(
        "duration",
        available_provider_keys={"youtubejs", "ytdlp"},
    )
    assert second == first


def test_unknown_field_has_no_provider_candidates() -> None:
    store = _store(_provider("youtubejs"))
    assert (
        store.field_provider_candidates(
            "not-a-field",
            available_provider_keys={"youtubejs"},
        )
        == ()
    )
