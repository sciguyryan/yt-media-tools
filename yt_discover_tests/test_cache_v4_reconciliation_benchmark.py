"""Deterministic contracts for the cache-v4 reconciliation benchmark harness."""

from pathlib import Path

from benchmarks.cache_v4_reconciliation import PROFILE_MEDIA_COUNTS, run_benchmark, source_media_indices


def test_cache_v4_benchmark_profiles_keep_heavy_shapes_out_of_routine_default() -> None:
    assert tuple(PROFILE_MEDIA_COUNTS) == ("small", "normal", "large", "huge")
    assert PROFILE_MEDIA_COUNTS["small"] < PROFILE_MEDIA_COUNTS["normal"] < PROFILE_MEDIA_COUNTS["large"]
    assert PROFILE_MEDIA_COUNTS["large"] < PROFILE_MEDIA_COUNTS["huge"]


def test_source_membership_is_deterministic_and_preserves_requested_identity_set() -> None:
    first = source_media_indices(23, 4, 50)
    second = source_media_indices(23, 4, 50)
    assert first == second
    assert {item for source in first for item in source} == set(range(23))
    assert set.intersection(*(set(source) for source in first)) == set(range(11))


def test_small_v4_shape_measures_deduplication_and_physical_storage(tmp_path: Path) -> None:
    result = run_benchmark(tmp_path / "benchmark.sqlite3", "test", 20, 4, 50)
    assert result.unique_media == 20
    assert result.source_entries > result.unique_media
    assert result.metrics.file_bytes > 0
    assert result.metrics.page_count > 0
    assert result.metrics.live_page_bytes > 0
    assert "cache_v4_media_entities" in result.metrics.table_bytes
    assert "cache_v4_ytdlp_collections" in result.metrics.table_bytes
