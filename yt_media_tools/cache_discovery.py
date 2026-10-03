"""Version-aware cache discovery for yt-discover startup.

Discovery is deliberately read-only. A filename identifies a schema candidate, but the
candidate is trusted only when its internal schema and completion state agree. Migration,
authorisation, cleanup and active runtime opening are later startup responsibilities.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .cache_v3_contract import validate_v3_database


LEGACY_V3_FILENAME = "metadata.sqlite3"
CURRENT_V4_FILENAME = "metadata-v4.sqlite3"
CURRENT_CACHE_SCHEMA_VERSION = 4
LEGACY_CACHE_SCHEMA_VERSION = 3

_REQUIRED_V4_TABLES = frozenset(
    {
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
    }
)


class CacheCandidateKind(Enum):
    """Role assigned to a recognised cache filename."""

    CURRENT = "current"
    HISTORICAL = "historical"


class CacheCandidateState(Enum):
    """Read-only validation state for a recognised cache candidate."""

    VALID = "valid"
    INCOMPLETE = "incomplete"
    VERSION_MISMATCH = "version_mismatch"
    CORRUPT = "corrupt"


class CacheResolutionKind(Enum):
    """Startup action implied by discovery without performing that action."""

    ACTIVE = "active"
    MIGRATION_REQUIRED = "migration_required"
    FRESH_REQUIRED = "fresh_required"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CacheCandidate:
    """One recognised cache file and the result of read-only validation."""

    path: Path
    kind: CacheCandidateKind
    expected_schema_version: int
    state: CacheCandidateState
    actual_schema_version: int | None = None
    migration_state: str | None = None
    detail: str | None = None

    @property
    def usable(self) -> bool:
        return self.state is CacheCandidateState.VALID


@dataclass(frozen=True)
class CacheDiscovery:
    """All recognised cache candidates in current-to-historical precedence order."""

    candidates: tuple[CacheCandidate, ...]


@dataclass(frozen=True)
class CacheResolution:
    """Read-only startup resolution produced from recognised candidates."""

    kind: CacheResolutionKind
    candidate: CacheCandidate | None = None
    blocking_candidate: CacheCandidate | None = None

    @property
    def active_path(self) -> Path | None:
        if self.kind is CacheResolutionKind.ACTIVE and self.candidate is not None:
            return self.candidate.path
        return None


def cache_paths(directory: Path) -> tuple[Path, Path]:
    """Return current v4 and legacy v3 paths in discovery precedence order."""
    root = directory.expanduser()
    return root / CURRENT_V4_FILENAME, root / LEGACY_V3_FILENAME


def _read_candidate(path: Path, kind: CacheCandidateKind, expected_version: int) -> CacheCandidate:
    try:
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                detail = str(integrity[0]) if integrity else "integrity check returned no result"
                return CacheCandidate(path, kind, expected_version, CacheCandidateState.CORRUPT, detail=detail)
            tables = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "cache_meta" not in tables:
                return CacheCandidate(
                    path,
                    kind,
                    expected_version,
                    CacheCandidateState.CORRUPT,
                    detail="cache_meta table is missing",
                )
            meta = dict(connection.execute("SELECT key, value FROM cache_meta"))
        finally:
            connection.close()
    except sqlite3.Error as exc:
        return CacheCandidate(path, kind, expected_version, CacheCandidateState.CORRUPT, detail=str(exc))

    raw_version = meta.get("schema_version")
    try:
        actual_version = int(raw_version)
    except (TypeError, ValueError):
        return CacheCandidate(
            path,
            kind,
            expected_version,
            CacheCandidateState.CORRUPT,
            detail="schema_version is missing or invalid",
        )
    migration_state = meta.get("migration_state")
    if actual_version != expected_version:
        return CacheCandidate(
            path,
            kind,
            expected_version,
            CacheCandidateState.VERSION_MISMATCH,
            actual_schema_version=actual_version,
            migration_state=migration_state,
            detail=f"filename expects schema v{expected_version}, database reports v{actual_version}",
        )
    if expected_version >= CURRENT_CACHE_SCHEMA_VERSION and migration_state != "complete":
        return CacheCandidate(
            path,
            kind,
            expected_version,
            CacheCandidateState.INCOMPLETE,
            actual_schema_version=actual_version,
            migration_state=migration_state,
            detail="current-schema cache is not marked complete",
        )
    if expected_version == CURRENT_CACHE_SCHEMA_VERSION:
        missing = _REQUIRED_V4_TABLES - tables
        if missing:
            return CacheCandidate(
                path,
                kind,
                expected_version,
                CacheCandidateState.CORRUPT,
                actual_schema_version=actual_version,
                migration_state=migration_state,
                detail=f"current-schema cache is missing required tables: {', '.join(sorted(missing))}",
            )
    if expected_version == LEGACY_CACHE_SCHEMA_VERSION:
        violations = validate_v3_database(path)
        if violations:
            detail = "; ".join(f"{item.code}: {item.detail}" for item in violations)
            return CacheCandidate(
                path,
                kind,
                expected_version,
                CacheCandidateState.CORRUPT,
                actual_schema_version=actual_version,
                migration_state=migration_state,
                detail=f"legacy cache is outside the recognised v3 contract: {detail}",
            )
    return CacheCandidate(
        path,
        kind,
        expected_version,
        CacheCandidateState.VALID,
        actual_schema_version=actual_version,
        migration_state=migration_state,
    )


def discover_caches(directory: Path) -> CacheDiscovery:
    """Inspect recognised cache filenames without creating or modifying any file."""
    current, legacy = cache_paths(directory)
    candidates: list[CacheCandidate] = []
    if current.exists():
        candidates.append(_read_candidate(current, CacheCandidateKind.CURRENT, CURRENT_CACHE_SCHEMA_VERSION))
    if legacy.exists():
        candidates.append(_read_candidate(legacy, CacheCandidateKind.HISTORICAL, LEGACY_CACHE_SCHEMA_VERSION))
    return CacheDiscovery(tuple(candidates))


def resolve_discovery(discovery: CacheDiscovery) -> CacheResolution:
    """Resolve discovery without migrating, deleting or creating cache state.

    The newest recognised candidate is authoritative for resolution. If it is damaged,
    incomplete or mismatched, startup is blocked rather than falling back to older state.
    """
    if not discovery.candidates:
        return CacheResolution(CacheResolutionKind.FRESH_REQUIRED)

    newest = discovery.candidates[0]
    if not newest.usable:
        return CacheResolution(CacheResolutionKind.BLOCKED, blocking_candidate=newest)
    if newest.kind is CacheCandidateKind.CURRENT:
        return CacheResolution(CacheResolutionKind.ACTIVE, candidate=newest)
    return CacheResolution(CacheResolutionKind.MIGRATION_REQUIRED, candidate=newest)


def discover_and_resolve(directory: Path) -> tuple[CacheDiscovery, CacheResolution]:
    """Perform read-only discovery and return its startup resolution."""
    discovery = discover_caches(directory)
    return discovery, resolve_discovery(discovery)
