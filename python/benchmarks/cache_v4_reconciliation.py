#!/usr/bin/env python3
"""Generate deterministic cache-v4 benchmark shapes and report physical storage facts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Any
import sys


def _metadata_cache_class() -> type:
    """Import MetadataCache after making direct script execution repository-aware."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from yt_media_tools.cache import MetadataCache

    return MetadataCache


PROFILE_MEDIA_COUNTS = {"small": 100, "normal": 1_000, "large": 10_000, "huge": 50_000}
DEFAULT_SOURCE_COUNT = 4
DEFAULT_OVERLAP_PERCENT = 50
BENCHMARK_TIME = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class DatabaseMetrics:
    """Physical and logical SQLite measurements for one benchmark database."""

    file_bytes: int
    page_size: int
    page_count: int
    freelist_pages: int
    freelist_bytes: int
    live_page_bytes: int
    table_bytes: dict[str, int]
    index_bytes: dict[str, int]


@dataclass(frozen=True)
class BenchmarkResult:
    """Machine-readable result for one deterministic cache-v4 benchmark shape."""

    profile: str
    requested_media: int
    source_count: int
    overlap_percent: int
    unique_media: int
    source_entries: int
    populate_seconds: float
    metrics: DatabaseMetrics


def _record(index: int) -> dict[str, Any]:
    """Build deterministic metadata with representative scalar and collection fields."""
    return {
        "id": f"bench-{index:08d}",
        "title": f"Benchmark video {index}",
        "upload_date": "20261004",
        "duration": 60 + index % 3_600,
        "view_count": index * 17,
        "like_count": index * 3,
        "uploader": f"Benchmark uploader {index % 23}",
        "uploader_id": f"uploader-{index % 23:03d}",
        "channel": f"Benchmark channel {index % 17}",
        "channel_id": f"channel-{index % 17:03d}",
        "timestamp": 1_759_579_200 + index,
        "tags": [f"tag-{index % 13}", f"tag-{(index + 3) % 13}"],
        "categories": [f"category-{index % 5}"],
        "formats": [
            {
                "format_id": "benchmark",
                "ext": "webm",
                "width": 1920,
                "height": 1080,
                "fps": 30,
                "vcodec": "vp9",
                "acodec": "opus",
            }
        ],
        "chapters": [{"start_time": 0, "end_time": 60, "title": "Opening"}],
        "thumbnails": [{"id": "0", "url": f"https://example.invalid/thumb/{index}.jpg"}],
    }


def source_media_indices(media_count: int, source_count: int, overlap_percent: int) -> tuple[tuple[int, ...], ...]:
    """Return deterministic source membership with a controlled shared-media fraction."""
    if source_count < 1:
        raise ValueError("source_count must be at least 1")
    if not 0 <= overlap_percent <= 100:
        raise ValueError("overlap_percent must be between 0 and 100")
    shared = media_count * overlap_percent // 100
    result = []
    for source_index in range(source_count):
        unique = tuple(index for index in range(shared + source_index, media_count, source_count))
        result.append(tuple(range(shared)) + unique)
    represented = {index for indices in result for index in indices}
    missing = tuple(index for index in range(media_count) if index not in represented)
    if missing:
        result[-1] = result[-1] + missing
    return tuple(result)


def _dbstat_bytes(connection: sqlite3.Connection, object_type: str) -> dict[str, int]:
    rows = connection.execute(
        """SELECT s.name, COALESCE(SUM(d.pgsize), 0)
           FROM sqlite_schema AS s LEFT JOIN dbstat AS d ON d.name = s.name
           WHERE s.type = ? GROUP BY s.name ORDER BY s.name""",
        (object_type,),
    ).fetchall()
    return {str(name): int(size) for name, size in rows}


def database_metrics(path: Path) -> DatabaseMetrics:
    """Measure file, freelist and b-tree storage without mutating the database."""
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
        try:
            table_bytes = _dbstat_bytes(connection, "table")
            index_bytes = _dbstat_bytes(connection, "index")
        except sqlite3.OperationalError:
            table_bytes = {}
            index_bytes = {}
        return DatabaseMetrics(
            file_bytes=path.stat().st_size,
            page_size=page_size,
            page_count=page_count,
            freelist_pages=freelist_pages,
            freelist_bytes=freelist_pages * page_size,
            live_page_bytes=(page_count - freelist_pages) * page_size,
            table_bytes=table_bytes,
            index_bytes=index_bytes,
        )
    finally:
        connection.close()


def run_benchmark(
    path: Path, profile: str, media_count: int, source_count: int, overlap_percent: int
) -> BenchmarkResult:
    """Populate one v4 database and return deterministic shape plus measured storage."""
    memberships = source_media_indices(media_count, source_count, overlap_percent)
    started = time.perf_counter()
    with _metadata_cache_class()(path) as cache:
        for source_index, indices in enumerate(memberships):
            source_url = f"https://benchmark.invalid/source/{source_index}"
            records = tuple(_record(index) for index in indices)
            cache.put_many(source_url, records, fetched_at=BENCHMARK_TIME)
            cache.record_source_entries(source_url, (record["id"] for record in records), observed_at=BENCHMARK_TIME)
            cache.record_source_observation(source_url, "benchmark", len(records), observed_at=BENCHMARK_TIME)
            cache.record_source_coverage(
                source_url, "benchmark", len(records), complete=True, reason="benchmark", observed_at=BENCHMARK_TIME
            )
    elapsed = time.perf_counter() - started
    connection = sqlite3.connect(path)
    try:
        unique_media = int(connection.execute("SELECT COUNT(*) FROM cache_v4_media_entities").fetchone()[0])
        source_entries = int(connection.execute("SELECT COUNT(*) FROM cache_v4_source_entries").fetchone()[0])
    finally:
        connection.close()
    return BenchmarkResult(
        profile,
        media_count,
        source_count,
        overlap_percent,
        unique_media,
        source_entries,
        elapsed,
        database_metrics(path),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_MEDIA_COUNTS), default="normal")
    parser.add_argument("--media-count", type=int, help="Override the selected profile with an exact media count.")
    parser.add_argument("--sources", type=int, default=DEFAULT_SOURCE_COUNT)
    parser.add_argument("--overlap-percent", type=int, default=DEFAULT_OVERLAP_PERCENT)
    parser.add_argument("--database", type=Path, help="Keep the generated benchmark database at this path.")
    parser.add_argument("--json", type=Path, help="Write the machine-readable result to this path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    media_count = args.media_count if args.media_count is not None else PROFILE_MEDIA_COUNTS[args.profile]
    if media_count < 1:
        raise SystemExit("--media-count must be at least 1")
    if args.database:
        path = args.database.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing database: {path}")
        result = run_benchmark(path, args.profile, media_count, args.sources, args.overlap_percent)
        payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    else:
        with tempfile.TemporaryDirectory(prefix="yt-discover-cache-v4-benchmark-") as directory:
            result = run_benchmark(
                Path(directory) / "cache-v4.sqlite3", args.profile, media_count, args.sources, args.overlap_percent
            )
            payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    print(payload)
    if args.json:
        args.json.expanduser().resolve().write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
