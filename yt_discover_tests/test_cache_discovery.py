"""Version-aware cache discovery and active-cache resolution tests."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from yt_media_tools.cache_discovery import (
    CURRENT_V4_FILENAME,
    LEGACY_V3_FILENAME,
    CacheCandidateKind,
    CacheCandidateState,
    CacheResolutionKind,
    cache_paths,
    discover_and_resolve,
)


V3_FIXTURE = Path(__file__).parent / "fixtures" / "cache_v3" / "canonical-valid-v3.sqlite3"


def _minimal_cache(path: Path, version: int, *, migration_state: str | None = None) -> None:
    connection = sqlite3.connect(path)
    with connection:
        connection.execute("CREATE TABLE cache_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO cache_meta VALUES('schema_version', ?)", (str(version),))
        if migration_state is not None:
            connection.execute("INSERT INTO cache_meta VALUES('migration_state', ?)", (migration_state,))
        if version == 4:
            for table in (
                "cache_v4_registry_meta",
                "cache_v4_providers",
                "cache_v4_media_entities",
                "cache_v4_ytdlp_metadata",
                "cache_v4_acquisition_state",
                "cache_v4_sources",
                "cache_v4_source_observations",
                "cache_v4_source_entries",
                "cache_v4_source_coverage",
                "cache_v4_source_frontiers",
                "cache_v4_raw_compatibility",
                "cache_v4_raw_migration_accounting",
            ):
                connection.execute(f'CREATE TABLE "{table}"(placeholder INTEGER)')
    connection.close()


def test_cache_paths_put_current_v4_before_unversioned_legacy_v3(tmp_path: Path) -> None:
    assert cache_paths(tmp_path) == (tmp_path / CURRENT_V4_FILENAME, tmp_path / LEGACY_V3_FILENAME)


def test_no_recognised_cache_requires_fresh_current_cache_without_creating_it(tmp_path: Path) -> None:
    discovery, resolution = discover_and_resolve(tmp_path)
    assert discovery.candidates == ()
    assert resolution.kind is CacheResolutionKind.FRESH_REQUIRED
    assert list(tmp_path.iterdir()) == []


def test_complete_v4_is_the_only_active_cache_even_when_legacy_v3_exists(tmp_path: Path) -> None:
    current, legacy = cache_paths(tmp_path)
    _minimal_cache(current, 4, migration_state="complete")
    shutil.copy2(V3_FIXTURE, legacy)

    discovery, resolution = discover_and_resolve(tmp_path)

    assert [item.kind for item in discovery.candidates] == [CacheCandidateKind.CURRENT, CacheCandidateKind.HISTORICAL]
    assert resolution.kind is CacheResolutionKind.ACTIVE
    assert resolution.active_path == current


def test_valid_legacy_v3_requires_migration_and_is_not_an_active_cache(tmp_path: Path) -> None:
    _, legacy = cache_paths(tmp_path)
    shutil.copy2(V3_FIXTURE, legacy)

    _, resolution = discover_and_resolve(tmp_path)

    assert resolution.kind is CacheResolutionKind.MIGRATION_REQUIRED
    assert resolution.candidate is not None
    assert resolution.candidate.path == legacy
    assert resolution.active_path is None


def test_incomplete_v4_blocks_fallback_to_valid_v3(tmp_path: Path) -> None:
    current, legacy = cache_paths(tmp_path)
    _minimal_cache(current, 4, migration_state="incomplete")
    shutil.copy2(V3_FIXTURE, legacy)

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.INCOMPLETE
    assert resolution.kind is CacheResolutionKind.BLOCKED
    assert resolution.blocking_candidate == discovery.candidates[0]
    assert resolution.active_path is None


def test_v4_filename_with_v3_internal_schema_blocks_fallback(tmp_path: Path) -> None:
    current, legacy = cache_paths(tmp_path)
    _minimal_cache(current, 3)
    shutil.copy2(V3_FIXTURE, legacy)

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.VERSION_MISMATCH
    assert discovery.candidates[0].actual_schema_version == 3
    assert resolution.kind is CacheResolutionKind.BLOCKED


def test_legacy_filename_with_wrong_internal_schema_is_not_a_migration_candidate(tmp_path: Path) -> None:
    _, legacy = cache_paths(tmp_path)
    _minimal_cache(legacy, 4, migration_state="complete")

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.VERSION_MISMATCH
    assert resolution.kind is CacheResolutionKind.BLOCKED


def test_corrupt_current_candidate_blocks_legacy_fallback(tmp_path: Path) -> None:
    current, legacy = cache_paths(tmp_path)
    current.write_bytes(b"not a sqlite database")
    shutil.copy2(V3_FIXTURE, legacy)

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.CORRUPT
    assert resolution.kind is CacheResolutionKind.BLOCKED
    assert resolution.blocking_candidate is not None
    assert resolution.blocking_candidate.path == current


def test_discovery_is_read_only_for_recognised_candidates(tmp_path: Path) -> None:
    current, legacy = cache_paths(tmp_path)
    _minimal_cache(current, 4, migration_state="complete")
    shutil.copy2(V3_FIXTURE, legacy)
    before = {path: path.read_bytes() for path in (current, legacy)}

    discover_and_resolve(tmp_path)

    assert {path: path.read_bytes() for path in (current, legacy)} == before


def test_complete_v4_missing_required_structure_is_corrupt(tmp_path: Path) -> None:
    current, _ = cache_paths(tmp_path)
    connection = sqlite3.connect(current)
    with connection:
        connection.execute("CREATE TABLE cache_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO cache_meta VALUES('schema_version', '4')")
        connection.execute("INSERT INTO cache_meta VALUES('migration_state', 'complete')")
    connection.close()

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.CORRUPT
    assert "missing required tables" in (discovery.candidates[0].detail or "")
    assert resolution.kind is CacheResolutionKind.BLOCKED


def test_invalid_legacy_v3_contract_blocks_fresh_cache_creation(tmp_path: Path) -> None:
    _, legacy = cache_paths(tmp_path)
    shutil.copy2(V3_FIXTURE, legacy)
    connection = sqlite3.connect(legacy)
    with connection:
        connection.execute(
            "UPDATE source_entries SET source_index=0 WHERE rowid=(SELECT rowid FROM source_entries LIMIT 1)"
        )
    connection.close()

    discovery, resolution = discover_and_resolve(tmp_path)

    assert discovery.candidates[0].state is CacheCandidateState.CORRUPT
    assert "source-entry-order" in (discovery.candidates[0].detail or "")
    assert resolution.kind is CacheResolutionKind.BLOCKED
