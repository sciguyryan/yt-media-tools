"""Cache-v4 entity identity and provider metadata storage tests."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from yt_media_tools.cache_entity_store import (
    AcquisitionOutcome,
    CacheV4EntityStore,
    FieldObservationKind,
)
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
    assert "cache_v4_acquisition_state" in tables
    assert store.acquisition_state(provider, entity.entity_id, "basic-info") is None
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


def test_missing_acquisition_state_means_not_yet_acquired() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    assert store.acquisition_state(provider, entity.entity_id, "basic-info") is None


def test_success_records_group_resolution_time() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)
    state = store.acquisition_state(provider, entity.entity_id, "basic-info")
    assert state is not None
    assert state.outcome is AcquisitionOutcome.SUCCESS
    assert state.last_attempt_at == acquired_at
    assert state.last_success_at == acquired_at
    assert state.failure_category is None


def test_failed_refresh_preserves_previous_success() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    success_at = datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)
    failed_at = success_at + timedelta(minutes=10)
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=success_at)
    store.record_acquisition_failure(
        provider, entity.entity_id, "basic-info", attempted_at=failed_at, category="provider-error"
    )
    state = store.acquisition_state(provider, entity.entity_id, "basic-info")
    assert state is not None
    assert state.outcome is AcquisitionOutcome.FAILED
    assert state.last_attempt_at == failed_at
    assert state.last_success_at == success_at
    assert state.failure_category == "provider-error"


def test_success_after_failure_clears_failure_state() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    failed_at = datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)
    success_at = failed_at + timedelta(minutes=10)
    store.record_acquisition_failure(
        provider, entity.entity_id, "basic-info", attempted_at=failed_at, category="provider-error"
    )
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=success_at)
    state = store.acquisition_state(provider, entity.entity_id, "basic-info")
    assert state is not None
    assert state.outcome is AcquisitionOutcome.SUCCESS
    assert state.last_success_at == success_at
    assert state.failure_category is None


def test_acquisition_groups_are_independent() -> None:
    basic = AcquisitionGroupDefinition("basic-info")
    formats = AcquisitionGroupDefinition("formats")
    provider = replace(
        _provider(),
        acquisition_groups=(basic, formats),
    )
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 12, 30, tzinfo=timezone.utc)
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)
    assert store.acquisition_state(provider, entity.entity_id, "basic-info") is not None
    assert store.acquisition_state(provider, entity.entity_id, "formats") is None


def test_acquisition_state_rejects_undeclared_group_and_naive_time() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    with pytest.raises(ValueError, match="does not declare acquisition group"):
        store.record_acquisition_success(provider, entity.entity_id, "formats", acquired_at=datetime.now(timezone.utc))
    with pytest.raises(ValueError, match="timezone-aware"):
        store.record_acquisition_success(
            provider, entity.entity_id, "basic-info", acquired_at=datetime(2026, 9, 30, 12, 30)
        )


def test_acquisition_attempt_time_cannot_move_backwards() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    later = datetime(2026, 9, 30, 13, 0, tzinfo=timezone.utc)
    earlier = later - timedelta(minutes=1)
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=later)
    with pytest.raises(ValueError, match="cannot be recorded earlier"):
        store.record_acquisition_failure(
            provider, entity.entity_id, "basic-info", attempted_at=earlier, category="provider-error"
        )


def test_acquisition_state_is_deleted_with_entity() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=datetime.now(timezone.utc))
    store.connection.execute("DELETE FROM cache_v4_media_entities WHERE entity_id = ?", (entity.entity_id,))
    store.connection.commit()
    count = store.connection.execute("SELECT COUNT(*) FROM cache_v4_acquisition_state").fetchone()[0]
    assert count == 0


def test_database_rejects_provider_group_identity_mismatch() -> None:
    first = _provider("first")
    second = _provider("second")
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((first, second))
    store = CacheV4EntityStore(connection, registry)
    store.initialise((first, second))
    entity = store.get_or_create_entity("youtube", "abc123")
    provider_id = connection.execute(
        "SELECT provider_id FROM cache_v4_providers WHERE provider_key = 'first'"
    ).fetchone()[0]
    group_id = connection.execute(
        """
        SELECT g.acquisition_group_id
        FROM cache_v4_acquisition_groups AS g
        JOIN cache_v4_providers AS p ON p.provider_id = g.provider_id
        WHERE p.provider_key = 'second' AND g.group_key = 'basic-info'
        """
    ).fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError, match="does not belong"):
        connection.execute(
            """
            INSERT INTO cache_v4_acquisition_state(
                entity_id, provider_id, acquisition_group_id, outcome,
                last_attempt_at, last_success_at, failure_category
            ) VALUES (?, ?, ?, 'failed', ?, NULL, 'provider-error')
            """,
            (entity.entity_id, provider_id, group_id, "2026-09-30T12:30:00+00:00"),
        )


def test_field_observation_distinguishes_unsupported_inapplicable_and_not_acquired() -> None:
    provider = _provider()
    _, store = _stores(provider)
    youtube = store.get_or_create_entity("youtube", "abc123")
    twitch = store.get_or_create_entity("twitch", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    assert (
        store.field_observation(provider, youtube.entity_id, "made_up", as_of=now).kind
        is FieldObservationKind.UNSUPPORTED
    )
    assert (
        store.field_observation(provider, twitch.entity_id, "duration", as_of=now).kind
        is FieldObservationKind.INAPPLICABLE
    )
    assert (
        store.field_observation(provider, youtube.entity_id, "duration", as_of=now).kind
        is FieldObservationKind.NOT_ACQUIRED
    )


def test_successful_group_distinguishes_value_and_known_null() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(provider, entity.entity_id, {"duration": 0, "title": None})
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)

    duration = store.field_observation(provider, entity.entity_id, "duration", as_of=acquired_at)
    title = store.field_observation(provider, entity.entity_id, "title", as_of=acquired_at)
    assert duration.kind is FieldObservationKind.VALUE
    assert duration.value == 0
    assert duration.observed_at == acquired_at
    assert title.kind is FieldObservationKind.KNOWN_NULL
    assert title.value is None
    assert title.observed_at == acquired_at


def test_failed_first_acquisition_is_not_known_null() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    attempted_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(provider, entity.entity_id, {"title": None})
    store.record_acquisition_failure(
        provider, entity.entity_id, "basic-info", attempted_at=attempted_at, category="provider-error"
    )

    observation = store.field_observation(provider, entity.entity_id, "title", as_of=attempted_at)
    assert observation.kind is FieldObservationKind.FAILED_ACQUISITION
    assert observation.observed_at is None
    assert observation.latest_attempt_failed
    assert observation.failure_category == "provider-error"


def test_failed_refresh_preserves_fresh_observation_and_failure_fact() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    failed_at = acquired_at + timedelta(minutes=10)
    store.write_provider_metadata(provider, entity.entity_id, {"title": "Still usable"})
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)
    store.record_acquisition_failure(
        provider, entity.entity_id, "basic-info", attempted_at=failed_at, category="timeout"
    )

    observation = store.field_observation(provider, entity.entity_id, "title", as_of=failed_at)
    assert observation.kind is FieldObservationKind.VALUE
    assert observation.value == "Still usable"
    assert observation.observed_at == acquired_at
    assert observation.latest_attempt_failed
    assert observation.failure_category == "timeout"


def test_field_freshness_is_derived_from_last_success_and_effective_policy() -> None:
    provider = _provider()
    registry, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(provider, entity.entity_id, {"duration": 42})
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)

    assert (
        store.field_observation(
            provider, entity.entity_id, "duration", as_of=acquired_at + timedelta(seconds=3600)
        ).kind
        is FieldObservationKind.VALUE
    )
    stale = store.field_observation(provider, entity.entity_id, "duration", as_of=acquired_at + timedelta(seconds=3601))
    assert stale.kind is FieldObservationKind.STALE
    assert stale.value == 42
    assert stale.observed_at == acquired_at

    registry.set_field_overrides("ytdlp", "duration", freshness=FreshnessPolicy.immutable())
    assert (
        store.field_observation(provider, entity.entity_id, "duration", as_of=acquired_at + timedelta(days=365)).kind
        is FieldObservationKind.VALUE
    )

    registry.set_field_overrides("ytdlp", "duration", freshness=FreshnessPolicy.always_refresh())
    assert (
        store.field_observation(provider, entity.entity_id, "duration", as_of=acquired_at).kind
        is FieldObservationKind.STALE
    )


def test_success_without_provider_metadata_row_is_rejected_as_inconsistent() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)

    with pytest.raises(RegistryContractError, match="successful acquisition state"):
        store.field_observation(provider, entity.entity_id, "duration", as_of=acquired_at)


def test_unknown_source_context_does_not_manufacture_inapplicability() -> None:
    provider = replace(
        _provider(),
        applicability=ProviderApplicability(
            services=frozenset({"youtube"}),
            source_kinds=frozenset({"channel"}),
            facets=frozenset({"videos"}),
            required_source_traits=frozenset({"ordered"}),
        ),
    )
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)

    assert (
        store.field_observation(provider, entity.entity_id, "duration", as_of=now).kind
        is FieldObservationKind.NOT_ACQUIRED
    )
    assert (
        store.field_observation(provider, entity.entity_id, "duration", as_of=now, source_kind="playlist").kind
        is FieldObservationKind.INAPPLICABLE
    )
    assert (
        store.field_observation(
            provider,
            entity.entity_id,
            "duration",
            as_of=now,
            source_kind="channel",
            facet="videos",
            source_traits=frozenset(),
        ).kind
        is FieldObservationKind.INAPPLICABLE
    )


def _resolution_stores(
    *providers: ProviderDefinition,
) -> tuple[CacheV4RegistryStore, CacheV4EntityStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile(providers)
    store = CacheV4EntityStore(connection, registry)
    store.initialise(providers)
    return registry, store


def test_field_resolution_uses_registry_priority_for_fresh_values() -> None:
    first = _provider("first")
    second = _provider("second")
    registry, store = _resolution_stores(first, second)
    registry.set_provider_policy("first", priority=10)
    registry.set_provider_policy("second", priority=20)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    for provider, title in ((first, "First"), (second, "Second")):
        store.write_provider_metadata(provider, entity.entity_id, {"title": title})
        store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((first, second), entity.entity_id, "title", as_of=now)
    assert resolved.resolved
    assert resolved.provider_key == "second"
    assert resolved.observation is not None
    assert resolved.observation.value == "Second"


def test_field_resolution_known_null_does_not_hide_lower_priority_value() -> None:
    first = _provider("first")
    second = _provider("second")
    registry, store = _resolution_stores(first, second)
    registry.set_provider_policy("first", priority=20)
    registry.set_provider_policy("second", priority=10)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(first, entity.entity_id, {"title": None})
    store.write_provider_metadata(second, entity.entity_id, {"title": "Fallback"})
    for provider in (first, second):
        store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((first, second), entity.entity_id, "title", as_of=now)
    assert resolved.provider_key == "second"
    assert resolved.observation is not None
    assert resolved.observation.kind is FieldObservationKind.VALUE
    assert resolved.observation.value == "Fallback"


def test_field_resolution_returns_known_null_when_no_fresh_value_exists() -> None:
    first = _provider("first")
    second = _provider("second")
    registry, store = _resolution_stores(first, second)
    registry.set_provider_policy("first", priority=20)
    registry.set_provider_policy("second", priority=10)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    for provider in (first, second):
        store.write_provider_metadata(provider, entity.entity_id, {"title": None})
        store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((first, second), entity.entity_id, "title", as_of=now)
    assert resolved.resolved
    assert resolved.provider_key == "first"
    assert resolved.observation is not None
    assert resolved.observation.kind is FieldObservationKind.KNOWN_NULL


def test_field_resolution_prefers_fresh_lower_priority_value_over_stale_value() -> None:
    first = _provider("first")
    second = _provider("second")
    registry, store = _resolution_stores(first, second)
    registry.set_provider_policy("first", priority=20)
    registry.set_provider_policy("second", priority=10)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(first, entity.entity_id, {"title": "Stale preferred"})
    store.record_acquisition_success(first, entity.entity_id, "basic-info", acquired_at=now - timedelta(hours=2))
    store.write_provider_metadata(second, entity.entity_id, {"title": "Fresh fallback"})
    store.record_acquisition_success(second, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((first, second), entity.entity_id, "title", as_of=now)
    assert resolved.provider_key == "second"
    assert resolved.observation is not None
    assert resolved.observation.value == "Fresh fallback"


def test_field_resolution_exposes_stale_fallback_as_unresolved() -> None:
    provider = _provider()
    _, store = _stores(provider)
    entity = store.get_or_create_entity("youtube", "abc123")
    acquired_at = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.write_provider_metadata(provider, entity.entity_id, {"title": "Old"})
    store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=acquired_at)

    resolved = store.resolve_field((provider,), entity.entity_id, "title", as_of=acquired_at + timedelta(hours=2))
    assert not resolved.resolved
    assert resolved.provider_key == "ytdlp"
    assert resolved.observation is not None
    assert resolved.observation.kind is FieldObservationKind.STALE
    assert resolved.observation.value == "Old"


def test_field_resolution_skips_failed_unacquired_and_inapplicable_candidates() -> None:
    failed = _provider("failed")
    fallback = _provider("fallback")
    registry, store = _resolution_stores(failed, fallback)
    registry.set_provider_policy("failed", priority=20)
    registry.set_provider_policy("fallback", priority=10)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    store.record_acquisition_failure(
        failed, entity.entity_id, "basic-info", attempted_at=now, category="provider-error"
    )
    store.write_provider_metadata(fallback, entity.entity_id, {"title": "Usable"})
    store.record_acquisition_success(fallback, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((failed, fallback), entity.entity_id, "title", as_of=now)
    assert resolved.provider_key == "fallback"
    assert resolved.observation is not None
    assert resolved.observation.value == "Usable"


def test_field_resolution_uses_registration_order_for_equal_priority() -> None:
    first = _provider("first")
    second = _provider("second")
    _, store = _resolution_stores(first, second)
    entity = store.get_or_create_entity("youtube", "abc123")
    now = datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc)
    for provider, title in ((first, "First"), (second, "Second")):
        store.write_provider_metadata(provider, entity.entity_id, {"title": title})
        store.record_acquisition_success(provider, entity.entity_id, "basic-info", acquired_at=now)

    resolved = store.resolve_field((second, first), entity.entity_id, "title", as_of=now)
    assert resolved.provider_key == "first"
    assert resolved.observation is not None
    assert resolved.observation.value == "First"


def test_source_facet_identity_is_stable_and_distinct() -> None:
    provider = _provider()
    _, store = _stores(provider)
    videos = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    again = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    shorts = store.get_or_create_source("https://example.invalid/channel", "channel", facet="shorts")
    assert again == videos
    assert shorts.source_id != videos.source_id


def test_source_observation_does_not_create_frontier_or_coverage_claim() -> None:
    provider = _provider()
    _, store = _stores(provider)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    observed_at = datetime(2026, 9, 30, 15, 0, tzinfo=timezone.utc)
    store.record_source_observation(source, 3, observed_at=observed_at)

    observation = store.source_observation(source)
    assert observation is not None
    assert observation.observed_entries == 3
    assert observation.last_observed_at == observed_at
    assert store.connection.execute("SELECT COUNT(*) FROM cache_v4_source_coverage").fetchone()[0] == 0
    assert store.connection.execute("SELECT COUNT(*) FROM cache_v4_source_frontiers").fetchone()[0] == 0


def test_source_entries_reference_stable_entities_not_provider_metadata() -> None:
    provider = _provider()
    _, store = _stores(provider)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    first = store.get_or_create_entity("youtube", "first")
    second = store.get_or_create_entity("youtube", "second")

    assert store.replace_source_entries(source, (first.entity_id, second.entity_id)) == 2
    assert store.source_entry_ids(source) == (first.entity_id, second.entity_id)
    assert store.provider_metadata(provider, first.entity_id) is None


def test_pruning_provider_metadata_cannot_erase_source_membership() -> None:
    provider = _provider()
    _, store = _stores(provider)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    entity = store.get_or_create_entity("youtube", "abc123")
    store.replace_source_entries(source, (entity.entity_id,))
    store.write_provider_metadata(provider, entity.entity_id, {"title": "Temporary"})

    store.connection.execute(f'DELETE FROM "{provider.metadata_table}" WHERE entity_id = ?', (entity.entity_id,))
    store.connection.commit()

    assert store.provider_metadata(provider, entity.entity_id) is None
    assert store.source_entry_ids(source) == (entity.entity_id,)
    assert store.entity("youtube", "abc123") == entity


def test_source_membership_prevents_entity_cascade_deletion() -> None:
    provider = _provider()
    _, store = _stores(provider)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    entity = store.get_or_create_entity("youtube", "abc123")
    store.replace_source_entries(source, (entity.entity_id,))

    with pytest.raises(sqlite3.IntegrityError):
        store.connection.execute("DELETE FROM cache_v4_media_entities WHERE entity_id = ?", (entity.entity_id,))
