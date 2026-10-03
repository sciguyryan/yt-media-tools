"""Historical v3-to-v4 fact mapping and composition-aware preflight analysis."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3

from .cache import MetadataCache
from .cache_v4_ytdlp import STABLE_COLLECTION_EQUIVALENTS, normalise_registered_metadata


@dataclass(frozen=True)
class V3Composition:
    """Facts that materially affect the size of a v4 destination."""

    metadata_records: int
    distinct_media: int
    source_observations: int
    source_entries: int
    source_coverage: int
    source_frontiers: int
    raw_json_bytes: int
    registered_json_bytes: int
    registered_collection_json_bytes: int


@dataclass(frozen=True)
class V4SpaceEstimate:
    """Explainable estimate derived from source composition and real v4 storage."""

    composition: V3Composition
    fixed_schema_bytes: int
    migrated_data_bytes: int
    index_and_page_reserve_bytes: int

    @property
    def required_bytes(self) -> int:
        return self.fixed_schema_bytes + self.migrated_data_bytes + self.index_and_page_reserve_bytes


def analyse_v3_composition(path: Path) -> V3Composition:
    """Measure v3 facts and the registered material that survives into v4."""
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT raw_json FROM metadata_records").fetchall()
        raw_bytes = 0
        registered_bytes = 0
        collection_bytes = 0
        for (raw_json,) in rows:
            encoded = str(raw_json).encode("utf-8")
            raw_bytes += len(encoded)
            record = json.loads(str(raw_json))
            registered, _ = normalise_registered_metadata(record)
            if registered:
                registered_bytes += len(
                    json.dumps(registered, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )
            collections = {name: record[name] for name in STABLE_COLLECTION_EQUIVALENTS if name in record}
            if collections:
                collection_bytes += len(
                    json.dumps(collections, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                )

        def scalar(sql: str) -> int:
            return int(connection.execute(sql).fetchone()[0])

        return V3Composition(
            metadata_records=len(rows),
            distinct_media=scalar("SELECT COUNT(DISTINCT video_id) FROM metadata_records"),
            source_observations=scalar("SELECT COUNT(*) FROM source_observations"),
            source_entries=scalar("SELECT COUNT(*) FROM source_entries"),
            source_coverage=scalar("SELECT COUNT(*) FROM source_coverage"),
            source_frontiers=scalar("SELECT COUNT(*) FROM source_frontiers"),
            raw_json_bytes=raw_bytes,
            registered_json_bytes=registered_bytes,
            registered_collection_json_bytes=collection_bytes,
        )
    finally:
        connection.close()


def _empty_v4_schema_bytes(directory: Path) -> tuple[int, int]:
    """Materialise the real current v4 schema and return its file and page sizes."""
    probe = directory / ".yt-discover-v4-sizing.sqlite3"
    if probe.exists():
        probe.unlink()
    try:
        with MetadataCache(probe):
            pass
        connection = sqlite3.connect(probe)
        try:
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
        finally:
            connection.close()
        return probe.stat().st_size, page_size
    finally:
        probe.unlink(missing_ok=True)
        Path(f"{probe}-wal").unlink(missing_ok=True)
        Path(f"{probe}-shm").unlink(missing_ok=True)


def estimate_v4_space(path: Path) -> V4SpaceEstimate:
    """Estimate destination space from actual v3 composition and current v4 schema."""
    composition = analyse_v3_composition(path)
    fixed_schema_bytes, page_size = _empty_v4_schema_bytes(path.parent)

    # The variable estimate deliberately follows v4 representation rather than v3 file size.
    # Registered scalar and collection metadata are measured directly from the historical
    # records, while source and acquisition rows use conservative
    # per-row allowances. Page/index reserve is tied to the rows v4 will actually index.
    migrated_data_bytes = (
        composition.registered_json_bytes
        + composition.registered_collection_json_bytes
        + composition.metadata_records * 192
        + composition.distinct_media * 128
        + composition.source_observations * 192
        + composition.source_entries * 128
        + composition.source_coverage * 160
        + composition.source_frontiers * 160
    )
    indexed_rows = (
        composition.distinct_media
        + composition.metadata_records
        + composition.source_observations
        + composition.source_entries
        + composition.source_coverage
        + composition.source_frontiers
    )
    reserve_pages = max(8, (indexed_rows + 31) // 32)
    return V4SpaceEstimate(
        composition=composition,
        fixed_schema_bytes=fixed_schema_bytes,
        migrated_data_bytes=migrated_data_bytes,
        index_and_page_reserve_bytes=reserve_pages * page_size,
    )
