"""Execute authorised cache startup decisions and establish the active v4 cache."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path

from .cache import initialise_v4_cache
from .cache_discovery import (
    CURRENT_CACHE_SCHEMA_VERSION,
    CURRENT_V4_FILENAME,
    LEGACY_CACHE_SCHEMA_VERSION,
    CacheResolutionKind,
    discover_and_resolve,
)
from .cache_migration import MigrationContext
from .cache_migration_support import MigrationEventSink, MigrationLog, run_logged_transition
from .cache_startup_policy import CacheStartupAction, CacheStartupDecision
from .cache_v3_to_v4_migration import execute_v3_to_v4

MIGRATION_LOG_FILENAME = "metadata-v3-to-v4-migration.jsonl"
STARTUP_LOCK_FILENAME = ".metadata-cache-startup.lock"


@contextmanager
def cache_startup_lock(directory: Path):
    """Serialise managed cache discovery and mutation across Discover processes."""
    root = directory.expanduser()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / STARTUP_LOCK_FILENAME
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            import fcntl
        except ImportError as exc:  # pragma: no cover - Discover currently targets POSIX deployment.
            raise RuntimeError("managed cache startup locking is unavailable on this platform") from exc
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class CacheMigrationRetentionPolicy:
    """File-retention policy applied around a startup migration."""

    retain_source_after_cutover: bool = False
    retain_failed_destination: bool = False


@dataclass(frozen=True)
class CacheStartupResult:
    """Completed startup state after any required creation or migration."""

    active_path: Path
    migrated: bool = False
    created: bool = False
    migration_log_path: Path | None = None


def _verified_active_path(directory: Path, expected: Path) -> Path:
    _, resolution = discover_and_resolve(directory)
    if resolution.kind is not CacheResolutionKind.ACTIVE or resolution.active_path != expected:
        detail = "current cache did not resolve as a complete active v4 database after startup work"
        if resolution.blocking_candidate is not None and resolution.blocking_candidate.detail:
            detail = resolution.blocking_candidate.detail
        raise RuntimeError(detail)
    return expected


def execute_cache_startup(
    directory: Path,
    decision: CacheStartupDecision,
    *,
    retention: CacheMigrationRetentionPolicy = CacheMigrationRetentionPolicy(),
    event_sinks: tuple[MigrationEventSink, ...] = (),
) -> CacheStartupResult:
    """Execute one authorised startup decision without beginning ordinary Discover work."""
    root = directory.expanduser()
    destination = root / CURRENT_V4_FILENAME

    if decision.action is CacheStartupAction.USE_ACTIVE:
        if decision.path is None:
            raise RuntimeError("active startup decision has no cache path")
        active = _verified_active_path(root, decision.path)
        return CacheStartupResult(active)

    if decision.action is CacheStartupAction.CREATE_FRESH:
        initialise_v4_cache(destination)
        active = _verified_active_path(root, destination)
        return CacheStartupResult(active, created=True)

    if decision.action is not CacheStartupAction.MIGRATE:
        detail = decision.detail or f"cache startup cannot continue: {decision.action.value}"
        raise RuntimeError(detail)
    if decision.path is None:
        raise RuntimeError("migration startup decision has no source path")

    source = decision.path
    context = MigrationContext(
        source_path=source,
        destination_path=destination,
        source_version=LEGACY_CACHE_SCHEMA_VERSION,
        target_version=CURRENT_CACHE_SCHEMA_VERSION,
    )
    log = MigrationLog(root / MIGRATION_LOG_FILENAME)
    try:
        result = run_logged_transition(context, execute_v3_to_v4, log=log, sinks=event_sinks)
        if not result.succeeded:
            raise RuntimeError(result.message or "cache migration did not produce a complete destination")
        active = _verified_active_path(root, destination)
    except BaseException:
        if not retention.retain_failed_destination:
            destination.unlink(missing_ok=True)
            Path(f"{destination}-wal").unlink(missing_ok=True)
            Path(f"{destination}-shm").unlink(missing_ok=True)
        raise

    if not retention.retain_source_after_cutover:
        source.unlink()
        Path(f"{source}-wal").unlink(missing_ok=True)
        Path(f"{source}-shm").unlink(missing_ok=True)
    return CacheStartupResult(active, migrated=True, migration_log_path=log.path)
