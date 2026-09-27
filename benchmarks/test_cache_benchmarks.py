"""Statistical benchmarks for deterministic local metadata-cache access."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from yt_media_tools.cache import MetadataCache

CACHE_COUNTS = (1, 100, 1_000)
CACHE_TIME = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


@pytest.mark.benchmark(group="cache-lookup")
@pytest.mark.parametrize("count", CACHE_COUNTS)
def test_cache_lookup_known_ids(benchmark, count: int, tmp_path: Path) -> None:
    """Measure the existing per-ID cache lookup path over a known key set."""
    path = tmp_path / f"metadata-{count}.sqlite3"
    records = [{"id": f"video-{index:05d}", "title": f"Video {index}", "view_count": index} for index in range(count)]
    ids = [record["id"] for record in records]
    with MetadataCache(path) as cache:
        assert cache.put_many("benchmark-source", records, fetched_at=CACHE_TIME) == count

        def lookup_all() -> dict[str, object]:
            return cache.get_many("benchmark-source", ids)

        benchmark.extra_info["benchmark_id"] = f"cache.lookup.{count}"
        result = benchmark(lookup_all)
        assert len(result) == count
        assert all(video_id in result for video_id in ids)
