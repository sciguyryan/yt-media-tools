"""Execution tests for cache-v4 maintenance plans."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from yt_media_tools.cache_entity_store import CacheV4EntityStore
from yt_media_tools.cache_maintenance import (
    CacheMaintenanceAuthorisation,
    CacheRetentionPolicy,
    MaintenanceAuthorisationError,
    execute_cache_maintenance,
    plan_cache_retention,
)
from yt_media_tools.cache_registry_store import CacheV4RegistryStore
from yt_media_tools.cache_v4_ytdlp import YTDLP_PROVIDER


NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _stores() -> tuple[sqlite3.Connection, CacheV4EntityStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((YTDLP_PROVIDER,))
    store = CacheV4EntityStore(connection, registry)
    store.initialise((YTDLP_PROVIDER,))
    return connection, store


def _metadata(store: CacheV4EntityStore, video_id: str, age_days: int) -> int:
    entity = store.get_or_create_entity("youtube", video_id)
    store.write_provider_metadata(YTDLP_PROVIDER, entity.entity_id, {"title": video_id})
    store.record_acquisition_success(
        YTDLP_PROVIDER, entity.entity_id, "detailed", acquired_at=NOW - timedelta(days=age_days)
    )
    return entity.entity_id


def test_execution_requires_authorisation_and_does_not_mutate_on_rejection() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    with pytest.raises(MaintenanceAuthorisationError):
        execute_cache_maintenance(connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation())

    assert store.provider_metadata(YTDLP_PROVIDER, entity_id) is not None


def test_provider_execution_removes_metadata_and_acquisition_as_one_contribution() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    result = execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert result.removed_provider_contributions == 1
    assert result.collected_entities == (entity_id,)
    assert store.provider_metadata(YTDLP_PROVIDER, entity_id) is None
    assert (
        connection.execute("SELECT 1 FROM cache_v4_acquisition_state WHERE entity_id = ?", (entity_id,)).fetchone()
        is None
    )


def test_provider_pruning_keeps_entity_still_referenced_by_source_state() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    store.replace_source_entries(source, (entity_id,))
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    result = execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert result.collected_entities == ()
    assert (
        connection.execute("SELECT 1 FROM cache_v4_media_entities WHERE entity_id = ?", (entity_id,)).fetchone()
        is not None
    )


def test_source_execution_removes_coherent_dependent_state_and_collects_entity() -> None:
    connection, store = _stores()
    entity = store.get_or_create_entity("youtube", "source-only")
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    store.record_source_observation(source, observed_at=NOW - timedelta(days=90), observed_entries=1)
    store.replace_source_entries(source, (entity.entity_id,))
    store.record_source_coverage(
        source,
        observed_at=NOW - timedelta(days=90),
        observed_entries=1,
        cached_entries=1,
        complete=True,
        reason="complete",
    )
    store.record_source_frontier(
        source,
        verified_at=NOW - timedelta(days=90),
        known_entries=1,
        head_entity_id=entity.entity_id,
        overlap_confirmations=1,
    )
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(source_max_age=timedelta(days=30)), now=NOW
    )

    result = execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert result.removed_source_states == 1
    assert result.collected_entities == (entity.entity_id,)
    for table in (
        "cache_v4_sources",
        "cache_v4_source_observations",
        "cache_v4_source_entries",
        "cache_v4_source_coverage",
        "cache_v4_source_frontiers",
    ):
        assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_combined_plan_collects_entity_only_after_provider_and_source_release() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    store.record_source_observation(source, observed_at=NOW - timedelta(days=90), observed_entries=1)
    store.replace_source_entries(source, (entity_id,))
    policy = CacheRetentionPolicy(provider_max_age=timedelta(days=30), source_max_age=timedelta(days=30))
    plan = plan_cache_retention(connection, (YTDLP_PROVIDER,), policy, now=NOW)

    result = execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert result.removed_units == plan.selected_units == 2
    assert result.collected_entities == (entity_id,)


def test_execution_consumes_plan_without_replanning_newly_eligible_state() -> None:
    connection, store = _stores()
    selected_id = _metadata(store, "selected", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )
    later_id = _metadata(store, "added-after-preview", 120)

    result = execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert result.collected_entities == (selected_id,)
    assert store.provider_metadata(YTDLP_PROVIDER, later_id) is not None


def test_configured_automatic_retention_uses_the_same_plan_executor() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    result = execute_cache_maintenance(
        connection,
        (YTDLP_PROVIDER,),
        plan,
        authorisation=CacheMaintenanceAuthorisation.configured_automatic_retention(),
    )

    assert result.planned_units == plan.selected_units == 1
    assert result.collected_entities == (entity_id,)


def test_execution_rolls_back_the_whole_plan_on_failure() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    source = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    store.record_source_observation(source, observed_at=NOW - timedelta(days=90), observed_entries=0)
    plan = plan_cache_retention(
        connection,
        (YTDLP_PROVIDER,),
        CacheRetentionPolicy(provider_max_age=timedelta(days=30), source_max_age=timedelta(days=30)),
        now=NOW,
    )
    connection.execute(
        "CREATE TRIGGER fail_source_prune BEFORE DELETE ON cache_v4_sources BEGIN SELECT RAISE(ABORT, 'boom'); END"
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError):
        execute_cache_maintenance(
            connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
        )

    assert store.provider_metadata(YTDLP_PROVIDER, entity_id) is not None
    assert (
        connection.execute("SELECT 1 FROM cache_v4_acquisition_state WHERE entity_id = ?", (entity_id,)).fetchone()
        is not None
    )
    assert (
        connection.execute("SELECT 1 FROM cache_v4_sources WHERE source_id = ?", (source.source_id,)).fetchone()
        is not None
    )


def test_large_explicit_plan_requires_confirmation_or_noninteractive_pre_authorisation() -> None:
    from yt_media_tools.cache_maintenance import authorise_explicit_maintenance

    connection, store = _stores()
    _metadata(store, "old-a", 90)
    _metadata(store, "old-b", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    with pytest.raises(MaintenanceAuthorisationError):
        authorise_explicit_maintenance(plan, confirmation_threshold=2, interactive=False)
    with pytest.raises(MaintenanceAuthorisationError):
        authorise_explicit_maintenance(plan, confirmation_threshold=2, interactive=True, confirm=lambda _: False)
    assert authorise_explicit_maintenance(
        plan, confirmation_threshold=2, interactive=True, confirm=lambda received: received is plan
    ).destructive
    assert authorise_explicit_maintenance(
        plan, confirmation_threshold=2, interactive=False, assume_yes=True
    ).destructive


def test_explicit_plan_below_caller_threshold_does_not_prompt() -> None:
    from yt_media_tools.cache_maintenance import authorise_explicit_maintenance

    connection, store = _stores()
    _metadata(store, "old", 90)
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    authorisation = authorise_explicit_maintenance(plan, confirmation_threshold=2, interactive=False)
    assert authorisation.destructive


def test_configured_retention_plans_and_executes_through_shared_functions() -> None:
    from yt_media_tools.cache_maintenance import run_configured_retention

    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    policy = CacheRetentionPolicy(provider_max_age=timedelta(days=30))

    plan, result = run_configured_retention(connection, (YTDLP_PROVIDER,), policy, now=NOW)

    assert plan.selected_units == result.planned_units == 1
    assert result.collected_entities == (entity_id,)


def test_provider_pruning_removes_provider_owned_raw_compatibility_material() -> None:
    connection, store = _stores()
    entity_id = _metadata(store, "old", 90)
    connection.execute(
        """
        CREATE TABLE cache_v4_raw_compatibility (
            source_url TEXT NOT NULL,
            video_id TEXT NOT NULL,
            acquired_at TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY(source_url, video_id)
        )
        """
    )
    connection.execute(
        "INSERT INTO cache_v4_raw_compatibility VALUES (?, ?, ?, ?)",
        ("source-a", "old", NOW.isoformat(), "{}"),
    )
    connection.execute(
        "INSERT INTO cache_v4_raw_compatibility VALUES (?, ?, ?, ?)",
        ("source-b", "old", NOW.isoformat(), "{}"),
    )
    connection.commit()
    plan = plan_cache_retention(
        connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(provider_max_age=timedelta(days=30)), now=NOW
    )

    execute_cache_maintenance(
        connection, (YTDLP_PROVIDER,), plan, authorisation=CacheMaintenanceAuthorisation.explicit()
    )

    assert (
        connection.execute("SELECT COUNT(*) FROM cache_v4_raw_compatibility WHERE video_id = 'old'").fetchone()[0] == 0
    )
    assert (
        connection.execute("SELECT 1 FROM cache_v4_media_entities WHERE entity_id = ?", (entity_id,)).fetchone() is None
    )
