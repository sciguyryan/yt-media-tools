"""Regression tests for the transitional v3-to-v4 source-state bridge."""

from datetime import datetime, timezone

from yt_media_tools.cache import MetadataCache


SOURCE = "https://example.invalid/channel"
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _count(cache: MetadataCache, table: str) -> int:
    return int(cache._db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_source_state_writes_are_mirrored_to_v4(tmp_path) -> None:
    with MetadataCache(tmp_path / "cache.sqlite") as cache:
        cache.record_source_observation(SOURCE, "channel", 2, observed_at=NOW)
        cache.record_source_entries(SOURCE, ["newer", "older"], observed_at=NOW)
        cache.record_source_coverage(SOURCE, "channel", 2, complete=True, reason="complete", observed_at=NOW)
        cache.record_source_frontier(
            SOURCE,
            "channel",
            ["newer", "older"],
            overlap_confirmations=2,
            verified_at=NOW,
        )

        assert _count(cache, "cache_v4_sources") == 1
        assert _count(cache, "cache_v4_source_observations") == 1
        assert _count(cache, "cache_v4_source_entries") == 2
        assert _count(cache, "cache_v4_source_coverage") == 1
        assert _count(cache, "cache_v4_source_frontiers") == 1
        assert _count(cache, "cache_v4_media_entities") == 2


def test_bridge_is_idempotent(tmp_path) -> None:
    with MetadataCache(tmp_path / "cache.sqlite") as cache:
        cache.record_source_observation(SOURCE, "channel", 2, observed_at=NOW)
        cache.record_source_entries(SOURCE, ["newer", "older"], observed_at=NOW)

        cache._sync_v4_source_state()
        cache._sync_v4_source_state()

        assert _count(cache, "cache_v4_sources") == 1
        assert _count(cache, "cache_v4_source_entries") == 2
        assert _count(cache, "cache_v4_media_entities") == 2


def test_frontier_removal_is_mirrored_without_erasing_membership(tmp_path) -> None:
    with MetadataCache(tmp_path / "cache.sqlite") as cache:
        cache.record_source_entries(SOURCE, ["newer", "older"], observed_at=NOW)
        cache.record_source_frontier(
            SOURCE,
            "channel",
            ["newer", "older"],
            overlap_confirmations=1,
            verified_at=NOW,
        )
        cache.record_source_frontier(SOURCE, "channel", [], overlap_confirmations=0, verified_at=NOW)

        assert _count(cache, "cache_v4_source_frontiers") == 0
        assert _count(cache, "cache_v4_source_entries") == 2


def test_open_imports_existing_legacy_source_state(tmp_path) -> None:
    path = tmp_path / "cache.sqlite"
    with MetadataCache(path) as cache:
        cache.record_source_observation(SOURCE, "channel", 1, observed_at=NOW)
        cache.record_source_entries(SOURCE, ["video"], observed_at=NOW)
        cache._db().execute("DELETE FROM cache_v4_source_entries")
        cache._db().execute("DELETE FROM cache_v4_source_observations")
        cache._db().execute("DELETE FROM cache_v4_sources")
        cache._db().commit()

    with MetadataCache(path) as cache:
        assert _count(cache, "cache_v4_sources") == 1
        assert _count(cache, "cache_v4_source_observations") == 1
        assert _count(cache, "cache_v4_source_entries") == 1
