"""Cache-v4 maintenance policy and immutable selection-plan tests."""

from datetime import datetime, timedelta, timezone
import sqlite3

import pytest

from yt_media_tools.cache_entity_store import CacheV4EntityStore
from yt_media_tools.cache_maintenance import CacheRetentionPolicy, plan_cache_retention
from yt_media_tools.cache_registry_store import CacheV4RegistryStore
from yt_media_tools.cache_v4_ytdlp import YTDLP_PROVIDER


NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _stores() -> tuple[sqlite3.Connection, CacheV4EntityStore]:
    connection = sqlite3.connect(":memory:")
    registry = CacheV4RegistryStore(connection)
    registry.reconcile((YTDLP_PROVIDER,))
    store = CacheV4EntityStore(connection, registry)
    store.initialise((YTDLP_PROVIDER,))
    return connection, store


def _entity_with_metadata(
    store: CacheV4EntityStore,
    video_id: str,
    acquired_at: datetime,
) -> int:
    entity = store.get_or_create_entity("youtube", video_id)
    store.write_provider_metadata(YTDLP_PROVIDER, entity.entity_id, {"title": video_id})
    store.record_acquisition_success(YTDLP_PROVIDER, entity.entity_id, "detailed", acquired_at=acquired_at)
    return entity.entity_id


def test_retention_is_disabled_by_default() -> None:
    policy = CacheRetentionPolicy()
    assert not policy.enabled
    assert policy.provider_max_age is None
    assert policy.source_max_age is None


@pytest.mark.parametrize("field", ["provider_max_age", "source_max_age"])
def test_retention_windows_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        CacheRetentionPolicy(**{field: timedelta(0)})


def test_empty_policy_selects_nothing_without_mutation() -> None:
    connection, store = _stores()
    entity_id = _entity_with_metadata(store, "old", NOW - timedelta(days=90))
    before = connection.total_changes

    plan = plan_cache_retention(connection, (YTDLP_PROVIDER,), CacheRetentionPolicy(), now=NOW)

    assert plan.is_empty
    assert connection.total_changes == before
    assert (
        connection.execute("SELECT 1 FROM cache_v4_ytdlp_metadata WHERE entity_id = ?", (entity_id,)).fetchone()
        is not None
    )


def test_provider_retention_uses_most_recent_success_for_coherent_contribution() -> None:
    connection, store = _stores()
    old_id = _entity_with_metadata(store, "old", NOW - timedelta(days=90))
    _entity_with_metadata(store, "fresh", NOW - timedelta(days=2))

    plan = plan_cache_retention(
        connection,
        (YTDLP_PROVIDER,),
        CacheRetentionPolicy(provider_max_age=timedelta(days=30)),
        now=NOW,
    )

    assert [(item.provider_key, item.entity_id) for item in plan.provider_contributions] == [("yt-dlp", old_id)]
    assert plan.source_states == ()


def test_failed_refresh_does_not_make_old_provider_contribution_recent() -> None:
    connection, store = _stores()
    entity_id = _entity_with_metadata(store, "old", NOW - timedelta(days=90))
    store.record_acquisition_failure(
        YTDLP_PROVIDER,
        entity_id,
        "detailed",
        attempted_at=NOW - timedelta(days=1),
        category="temporary",
    )

    plan = plan_cache_retention(
        connection,
        (YTDLP_PROVIDER,),
        CacheRetentionPolicy(provider_max_age=timedelta(days=30)),
        now=NOW,
    )

    assert [item.entity_id for item in plan.provider_contributions] == [entity_id]
    assert plan.provider_contributions[0].last_success_at == NOW - timedelta(days=90)


def test_source_retention_selects_whole_source_facet_by_observation_age() -> None:
    connection, store = _stores()
    old = store.get_or_create_source("https://example.invalid/channel", "channel", facet="videos")
    fresh = store.get_or_create_source("https://example.invalid/channel", "channel", facet="live")
    store.record_source_observation(old, observed_at=NOW - timedelta(days=90), observed_entries=3)
    store.record_source_observation(fresh, observed_at=NOW - timedelta(days=2), observed_entries=1)

    plan = plan_cache_retention(
        connection,
        (YTDLP_PROVIDER,),
        CacheRetentionPolicy(source_max_age=timedelta(days=30)),
        now=NOW,
    )

    assert [(item.source_id, item.facet) for item in plan.source_states] == [(old.source_id, "videos")]
    assert plan.provider_contributions == ()


def test_cutoff_is_strictly_older_than_retention_window() -> None:
    connection, store = _stores()
    _entity_with_metadata(store, "boundary", NOW - timedelta(days=30))

    plan = plan_cache_retention(
        connection,
        (YTDLP_PROVIDER,),
        CacheRetentionPolicy(provider_max_age=timedelta(days=30)),
        now=NOW,
    )

    assert plan.is_empty


def test_planning_is_deterministic_and_read_only() -> None:
    connection, store = _stores()
    _entity_with_metadata(store, "b", NOW - timedelta(days=90))
    _entity_with_metadata(store, "a", NOW - timedelta(days=91))
    policy = CacheRetentionPolicy(provider_max_age=timedelta(days=30))
    before = connection.total_changes

    first = plan_cache_retention(connection, (YTDLP_PROVIDER,), policy, now=NOW)
    second = plan_cache_retention(connection, (YTDLP_PROVIDER,), policy, now=NOW)

    assert first == second
    assert connection.total_changes == before
    assert first.selected_units == 2
