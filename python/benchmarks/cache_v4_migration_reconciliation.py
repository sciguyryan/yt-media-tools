#!/usr/bin/env python3
"""Benchmark the real v3-to-v4 migration path using deterministic historical cache shapes."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
from typing import Any

PROFILE_ADDITIONAL_RECORDS = {"small": 100, "normal": 1_000, "large": 10_000, "huge": 50_000}


def _migration_api() -> tuple[type, type, Any, Any]:
    """Import migration APIs after making direct script execution repository-aware."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from yt_media_tools.cache_migration_support import MigrationContext, MigrationEventStream
    from yt_media_tools.cache_v3_to_v4_analysis import estimate_v4_space
    from yt_media_tools.cache_v3_to_v4_migration import execute_v3_to_v4

    return MigrationContext, MigrationEventStream, estimate_v4_space, execute_v3_to_v4


@dataclass(frozen=True)
class StorageMetrics:
    """Physical SQLite storage facts at one benchmark checkpoint."""

    file_bytes: int
    page_size: int
    page_count: int
    freelist_pages: int
    freelist_bytes: int
    live_page_bytes: int


@dataclass(frozen=True)
class MigrationBenchmarkResult:
    """Machine-readable measurements for one real v3-to-v4 migration."""

    profile: str
    additional_records: int
    source_bytes: int
    source_sha256_before: str
    source_sha256_after: str
    preflight_required_bytes: int
    migration_seconds: float
    verification_seconds: float
    phase_seconds: dict[str, float]
    stage_storage: dict[str, StorageMetrics]
    peak_observed_file_bytes: int
    before_compaction: StorageMetrics
    after_compaction: StorageMetrics
    preflight_to_peak_ratio: float
    preflight_to_final_ratio: float


def _storage_metrics(path: Path) -> StorageMetrics:
    connection = sqlite3.connect(path)
    try:
        page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
        freelist_pages = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
    finally:
        connection.close()
    return StorageMetrics(
        file_bytes=path.stat().st_size,
        page_size=page_size,
        page_count=page_count,
        freelist_pages=freelist_pages,
        freelist_bytes=freelist_pages * page_size,
        live_page_bytes=(page_count - freelist_pages) * page_size,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "yt_discover_tests"
        / "fixtures"
        / "cache_v3"
        / "canonical-valid-v3.sqlite3"
    )


def build_v3_shape(path: Path, additional_records: int) -> None:
    """Clone the permanent historical fixture and add deterministic metadata records."""
    if additional_records < 0:
        raise ValueError("additional_records must be non-negative")
    shutil.copy2(_fixture_path(), path)
    connection = sqlite3.connect(path)
    try:
        source_url, fetched_at, raw_json = connection.execute(
            "SELECT source_url, fetched_at, raw_json FROM metadata_records ORDER BY source_url, video_id LIMIT 1"
        ).fetchone()
        template = json.loads(str(raw_json))
        for index in range(additional_records):
            video_id = f"benchmark-{index:08d}"
            record = dict(template)
            record["id"] = video_id
            record["title"] = f"Benchmark record {index:08d}"
            connection.execute(
                "INSERT INTO metadata_records(source_url, video_id, fetched_at, raw_json) VALUES (?, ?, ?, ?)",
                (
                    source_url,
                    video_id,
                    fetched_at,
                    json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                ),
            )
        connection.commit()
    finally:
        connection.close()


def run_benchmark(profile: str, additional_records: int, directory: Path) -> MigrationBenchmarkResult:
    """Run the production migration and measure phase timing, storage churn and compaction."""
    MigrationContext, MigrationEventStream, estimate_v4_space, execute_v3_to_v4 = _migration_api()
    source = directory / "metadata-v3.sqlite3"
    destination = directory / "metadata-v4.sqlite3"
    build_v3_shape(source, additional_records)
    source_hash_before = _sha256(source)
    estimate = estimate_v4_space(source)

    stage_started: dict[str, float] = {}
    phase_seconds: dict[str, float] = {}
    stage_storage: dict[str, StorageMetrics] = {}
    peak_observed_file_bytes = 0

    def observe(event: Any) -> None:
        nonlocal peak_observed_file_bytes
        now = time.perf_counter()
        if event.kind == "start":
            stage_started[event.stage] = now
        elif event.kind == "complete" and event.stage in stage_started:
            phase_seconds[event.stage] = now - stage_started[event.stage]
        if destination.exists():
            peak_observed_file_bytes = max(peak_observed_file_bytes, destination.stat().st_size)
            if event.kind in {"progress", "complete"}:
                stage_storage[event.stage] = _storage_metrics(destination)

    started = time.perf_counter()
    result = execute_v3_to_v4(
        MigrationContext(source, destination, 3, 4),
        MigrationEventStream((observe,)),
    )
    migration_seconds = time.perf_counter() - started
    if not result.succeeded:
        raise RuntimeError("v3-to-v4 benchmark migration did not succeed")
    peak_observed_file_bytes = max(peak_observed_file_bytes, destination.stat().st_size)
    before = _storage_metrics(destination)

    connection = sqlite3.connect(destination)
    try:
        connection.execute("VACUUM")
    finally:
        connection.close()
    after = _storage_metrics(destination)

    required = int(estimate.required_bytes)
    return MigrationBenchmarkResult(
        profile=profile,
        additional_records=additional_records,
        source_bytes=source.stat().st_size,
        source_sha256_before=source_hash_before,
        source_sha256_after=_sha256(source),
        preflight_required_bytes=required,
        migration_seconds=migration_seconds,
        verification_seconds=phase_seconds.get("target validation", 0.0),
        phase_seconds=dict(sorted(phase_seconds.items())),
        stage_storage=dict(sorted(stage_storage.items())),
        peak_observed_file_bytes=peak_observed_file_bytes,
        before_compaction=before,
        after_compaction=after,
        preflight_to_peak_ratio=required / peak_observed_file_bytes if peak_observed_file_bytes else 0.0,
        preflight_to_final_ratio=required / after.file_bytes if after.file_bytes else 0.0,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=tuple(PROFILE_ADDITIONAL_RECORDS), default="normal")
    parser.add_argument(
        "--additional-records", type=int, help="Override the profile's additional metadata-record count."
    )
    parser.add_argument("--output", type=Path, help="Write the JSON result to this path as well as stdout.")
    parser.add_argument(
        "--keep-database", type=Path, help="Copy the generated v4 database to this path after measurement."
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    count = PROFILE_ADDITIONAL_RECORDS[args.profile] if args.additional_records is None else args.additional_records
    if count < 0:
        raise SystemExit("--additional-records must be non-negative")
    with tempfile.TemporaryDirectory(prefix="yt-discover-v4-migration-benchmark-") as temporary:
        directory = Path(temporary)
        result = run_benchmark(args.profile, count, directory)
        if args.keep_database:
            args.keep_database.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory / "metadata-v4.sqlite3", args.keep_database)
        payload = json.dumps(asdict(result), indent=2, sort_keys=True)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
