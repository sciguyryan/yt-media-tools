"""Shared SQLite maintenance measurements, policy and guarded execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sqlite3
import shutil
import time
import tomllib
from typing import Mapping

SCHEMA_VERSION = 1
CONFIG_FILENAME = "database-maintenance.toml"
DATABASE_KEYS = ("collection_state", "metadata_cache")
VACUUM_MODES = {0: "none", 1: "full", 2: "incremental"}


class MaintenancePolicyError(ValueError):
    """The explicit maintenance policy is invalid."""


class MaintenanceInspectionError(RuntimeError):
    """The database cannot be safely inspected."""


@dataclass(frozen=True)
class DatabaseThreshold:
    min_reclaimable_mib: int
    min_free_ratio: float


@dataclass(frozen=True)
class MaintenancePolicy:
    enabled: bool
    trigger: str
    strategy: str
    incremental_enabled: bool
    max_pages_per_run: int
    max_duration_seconds: int
    automatic_full: bool
    databases: Mapping[str, DatabaseThreshold]


@dataclass(frozen=True)
class DatabaseMeasurements:
    path: Path
    page_count: int
    freelist_count: int
    page_size: int
    auto_vacuum: str
    file_bytes: int
    wal_bytes: int

    @property
    def reclaimable_bytes(self) -> int:
        return self.freelist_count * self.page_size

    @property
    def free_page_ratio(self) -> float:
        return self.freelist_count / self.page_count if self.page_count else 0.0


@dataclass(frozen=True)
class MaintenanceDecision:
    eligible: bool
    action: str
    reason: str
    measurements: DatabaseMeasurements


def default_policy() -> MaintenancePolicy:
    """Use conservative defaults until representative workloads justify changes."""
    return MaintenancePolicy(
        enabled=True,
        trigger="post-operation",
        strategy="hybrid",
        incremental_enabled=True,
        max_pages_per_run=4096,
        max_duration_seconds=2,
        automatic_full=False,
        databases={
            "collection_state": DatabaseThreshold(32, 0.25),
            "metadata_cache": DatabaseThreshold(512, 0.30),
        },
    )


def _table(value: object, allowed: set[str], location: str) -> dict:
    if not isinstance(value, dict):
        raise MaintenancePolicyError(f"{location} must be a table")
    unknown = set(value) - allowed
    if unknown:
        raise MaintenancePolicyError(f"unknown {location} settings: {', '.join(sorted(unknown))}")
    return value


def _bool(value: object, location: str) -> bool:
    if type(value) is not bool:
        raise MaintenancePolicyError(f"{location} must be a boolean")
    return value


def _int(value: object, location: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise MaintenancePolicyError(f"{location} must be an integer >= {minimum}")
    return value


def parse_policy(text: str) -> MaintenancePolicy:
    """Parse a complete versioned policy without accepting unknown settings."""
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise MaintenancePolicyError(f"invalid maintenance TOML: {exc}") from exc
    root = _table(raw, {"schema_version", "maintenance", "databases"}, "root")
    if _int(root.get("schema_version"), "schema_version", minimum=1) != SCHEMA_VERSION:
        raise MaintenancePolicyError("unsupported maintenance policy schema version")
    defaults = default_policy()
    main = _table(root.get("maintenance", {}), {"enabled", "trigger", "strategy", "incremental", "full"}, "maintenance")
    incremental = _table(
        main.get("incremental", {}), {"enabled", "max_pages_per_run", "max_duration_seconds"}, "maintenance.incremental"
    )
    full = _table(main.get("full", {}), {"automatic"}, "maintenance.full")
    databases = _table(root.get("databases", {}), set(DATABASE_KEYS), "databases")
    trigger = main.get("trigger", defaults.trigger)
    strategy = main.get("strategy", defaults.strategy)
    if trigger != "post-operation" or strategy != "hybrid":
        raise MaintenancePolicyError("only post-operation hybrid maintenance is supported")
    automatic_full = _bool(full.get("automatic", False), "maintenance.full.automatic")
    if automatic_full:
        raise MaintenancePolicyError("automatic full vacuum is not supported")
    thresholds = {}
    for name in DATABASE_KEYS:
        entry = _table(databases.get(name, {}), {"min_reclaimable_mib", "min_free_ratio"}, f"databases.{name}")
        base = defaults.databases[name]
        ratio = entry.get("min_free_ratio", base.min_free_ratio)
        if type(ratio) not in (int, float) or not 0 <= ratio <= 1:
            raise MaintenancePolicyError(f"databases.{name}.min_free_ratio must be between 0 and 1")
        thresholds[name] = DatabaseThreshold(
            _int(entry.get("min_reclaimable_mib", base.min_reclaimable_mib), f"databases.{name}.min_reclaimable_mib"),
            float(ratio),
        )
    return MaintenancePolicy(
        enabled=_bool(main.get("enabled", defaults.enabled), "maintenance.enabled"),
        trigger=trigger,
        strategy=strategy,
        incremental_enabled=_bool(
            incremental.get("enabled", defaults.incremental_enabled), "maintenance.incremental.enabled"
        ),
        max_pages_per_run=_int(
            incremental.get("max_pages_per_run", defaults.max_pages_per_run),
            "maintenance.incremental.max_pages_per_run",
            minimum=1,
        ),
        max_duration_seconds=_int(
            incremental.get("max_duration_seconds", defaults.max_duration_seconds),
            "maintenance.incremental.max_duration_seconds",
            minimum=1,
        ),
        automatic_full=False,
        databases=thresholds,
    )


def default_config_path(*, environ: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    environment = os.environ if environ is None else environ
    configured = environment.get("XDG_CONFIG_HOME")
    root = (
        Path(configured).expanduser()
        if configured and Path(configured).is_absolute()
        else (home or Path.home()) / ".config"
    )
    return root / "yt-media-tools" / CONFIG_FILENAME


def load_policy(path: Path | None = None) -> MaintenancePolicy:
    """Absent optional policy uses defaults; an invalid explicit file fails closed."""
    source = default_config_path() if path is None else Path(path)
    try:
        return parse_policy(source.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if path is not None:
            raise MaintenancePolicyError(f"maintenance policy does not exist: {source}") from None
        return default_policy()
    except (OSError, UnicodeError) as exc:
        raise MaintenancePolicyError(f"cannot read maintenance policy {source}: {exc}") from exc


def inspect_database(path: Path) -> DatabaseMeasurements:
    """Read an existing SQLite database without creating or writing to it."""
    source = Path(path).resolve()
    if not source.is_file():
        raise MaintenanceInspectionError(f"database does not exist: {source}")
    try:
        # mode=ro prevents creation; query_only guards accidental future writes.
        with sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True, timeout=0.1) as connection:
            connection.execute("PRAGMA query_only=ON")
            page_count = int(connection.execute("PRAGMA page_count").fetchone()[0])
            freelist_count = int(connection.execute("PRAGMA freelist_count").fetchone()[0])
            page_size = int(connection.execute("PRAGMA page_size").fetchone()[0])
            vacuum = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
        if (
            vacuum not in VACUUM_MODES
            or page_count < freelist_count
            or page_count < 0
            or freelist_count < 0
            or page_size <= 0
        ):
            raise MaintenanceInspectionError("invalid SQLite page measurements")
        wal = Path(str(source) + "-wal")
        return DatabaseMeasurements(
            source,
            page_count,
            freelist_count,
            page_size,
            VACUUM_MODES[vacuum],
            source.stat().st_size,
            wal.stat().st_size if wal.exists() else 0,
        )
    except (sqlite3.Error, OSError) as exc:
        raise MaintenanceInspectionError(f"cannot inspect database {source}: {exc}") from exc


def decide_maintenance(
    measurements: DatabaseMeasurements, policy: MaintenancePolicy, database: str
) -> MaintenanceDecision:
    """Explain an automatic action without executing it."""
    if database not in DATABASE_KEYS:
        raise ValueError(f"unknown managed database: {database}")
    if not policy.enabled:
        reason = "automatic maintenance disabled"
    elif not policy.incremental_enabled:
        reason = "incremental maintenance disabled"
    elif measurements.auto_vacuum != "incremental":
        reason = "database does not support incremental vacuum; explicit conversion required"
    elif measurements.reclaimable_bytes < policy.databases[database].min_reclaimable_mib * 1024 * 1024:
        reason = "reclaimable bytes below threshold"
    elif measurements.free_page_ratio < policy.databases[database].min_free_ratio:
        reason = "free-page ratio below threshold"
    else:
        return MaintenanceDecision(True, "incremental_vacuum", "both reclamation thresholds met", measurements)
    return MaintenanceDecision(False, "none", reason, measurements)


def dry_run(path: Path, database: str, policy: MaintenancePolicy | None = None) -> MaintenanceDecision:
    """Read-only maintenance preview; never modify the database."""
    return decide_maintenance(inspect_database(path), policy or load_policy(), database)


@dataclass(frozen=True)
class MaintenanceOutcome:
    """Outcome of one opportunistic, post-operation maintenance attempt."""

    status: str
    reason: str
    pages_reclaimed: int = 0


def _try_maintenance_lock(handle: object) -> bool:
    """Acquire the advisory maintenance lock without waiting for other maintainers."""
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except (OSError, BlockingIOError):
        return False


def _release_maintenance_lock(handle: object) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def incremental_maintenance(
    path: Path,
    database: str,
    policy: MaintenancePolicy | None = None,
    *,
    clock=None,
) -> MaintenanceOutcome:
    """Attempt bounded post-operation reclamation; never create a missing database.

    The advisory lock serialises cooperating maintainers. SQLite's immediate
    write transaction and zero busy timeout independently protect against
    competing writers and readers requiring incompatible locks. Each vacuum
    statement is bounded to one page; the time budget is checked between them.
    """
    policy = policy if policy is not None else load_policy()
    clock = clock or time.monotonic
    source = Path(path).resolve()
    if not source.is_file():
        return MaintenanceOutcome("deferred", "database does not exist")
    lock_path = source.with_name(source.name + ".maintenance.lock")
    try:
        with lock_path.open("a+b") as handle:
            if not _try_maintenance_lock(handle):
                return MaintenanceOutcome("deferred", "another maintenance operation is active")
            try:
                decision = dry_run(source, database, policy)
                if not decision.eligible:
                    return MaintenanceOutcome("skipped", decision.reason)
                start = clock()
                reclaimed = 0
                # Use short, individual transactions rather than holding a write
                # lock for the whole page budget or wall-clock interval.
                for _ in range(policy.max_pages_per_run):
                    if clock() - start >= policy.max_duration_seconds:
                        break
                    try:
                        with sqlite3.connect(f"{source.as_uri()}?mode=rw", uri=True, timeout=0) as connection:
                            connection.execute("PRAGMA busy_timeout=0")
                            if connection.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
                                return MaintenanceOutcome("deferred", "incremental vacuum mode changed", reclaimed)
                            before = connection.execute("PRAGMA freelist_count").fetchone()[0]
                            if not before:
                                break
                            connection.execute("PRAGMA incremental_vacuum(1)")
                            after = connection.execute("PRAGMA freelist_count").fetchone()[0]
                            if after >= before:
                                break
                            reclaimed += before - after
                    except sqlite3.OperationalError as exc:
                        if getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                            return MaintenanceOutcome("deferred", "database is busy", reclaimed)
                        return MaintenanceOutcome("deferred", f"SQLite maintenance unavailable: {exc}", reclaimed)
                return MaintenanceOutcome("completed", "bounded incremental vacuum finished", reclaimed)
            finally:
                _release_maintenance_lock(handle)
    except (OSError, sqlite3.Error, MaintenanceInspectionError) as exc:
        return MaintenanceOutcome("deferred", f"maintenance unavailable: {exc}")


@dataclass(frozen=True)
class SQLiteStorageMeasurement:
    """Connection-local measurements used by the existing cache status contract."""

    page_size: int
    page_count: int
    free_pages: int
    database_bytes: int | None
    wal_bytes: int | None

    @property
    def reusable_bytes(self) -> int:
        return self.page_size * self.free_pages


@dataclass(frozen=True)
class CacheCompactionResult:
    """Compatibility result for the explicit Discover compaction command."""

    journal_mode: str
    auto_vacuum: str
    checkpoint_attempted: bool
    checkpoint_busy: int | None
    checkpoint_log_pages: int | None
    checkpointed_pages: int | None
    vacuum_performed: bool
    before: SQLiteStorageMeasurement
    after: SQLiteStorageMeasurement

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _optional_file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def measure_sqlite_storage(connection: sqlite3.Connection, path: Path) -> SQLiteStorageMeasurement:
    """Inspect the existing connection without altering its transaction state."""
    source = Path(path).expanduser()
    return SQLiteStorageMeasurement(
        page_size=int(connection.execute("PRAGMA page_size").fetchone()[0]),
        page_count=int(connection.execute("PRAGMA page_count").fetchone()[0]),
        free_pages=int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
        database_bytes=_optional_file_size(source),
        wal_bytes=_optional_file_size(Path(str(source) + "-wal")),
    )


def checkpoint_wal(connection: sqlite3.Connection, *, mode: str = "PASSIVE") -> tuple[int, int, int] | None:
    """Checkpoint an existing WAL database without changing journal mode."""
    if connection.in_transaction:
        raise RuntimeError("WAL checkpoint requires no active SQLite transaction")
    if mode not in {"PASSIVE", "TRUNCATE"}:
        raise ValueError("unsupported WAL checkpoint mode")
    if str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower() != "wal":
        return None
    row = connection.execute(f"PRAGMA wal_checkpoint({mode})").fetchone()
    if row is None:
        raise RuntimeError("WAL checkpoint returned no result")
    return tuple(int(value) for value in row)


def optimise_statistics(connection: sqlite3.Connection) -> None:
    """Request SQLite's own bounded query-planner statistics optimisation."""
    if connection.in_transaction:
        raise RuntimeError("statistics optimisation requires no active SQLite transaction")
    connection.execute("PRAGMA optimize")


def manual_full_vacuum(
    connection: sqlite3.Connection,
    path: Path,
    *,
    minimum_free_space_multiplier: float = 2.0,
) -> CacheCompactionResult:
    """Explicit full compaction shared by all SQLite-backed application commands.

    The caller must invoke this outside normal operations. A non-blocking
    advisory lock coordinates with incremental maintainers. SQLite remains the
    authority for other readers and writers; busy access fails rather than waits.
    """
    if connection.in_transaction:
        raise RuntimeError("cache compaction requires no active SQLite transaction")
    if not 1 <= minimum_free_space_multiplier < float("inf"):
        raise ValueError("full vacuum space multiplier must be at least one")
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    lock_path = source.with_name(source.name + ".maintenance.lock")
    with lock_path.open("a+b") as handle:
        if not _try_maintenance_lock(handle):
            raise RuntimeError("another database maintenance operation is active")
        try:
            connection.execute("PRAGMA busy_timeout=0")
            journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
            mode_value = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
            if mode_value not in VACUUM_MODES:
                raise RuntimeError("unsupported SQLite auto-vacuum mode")
            mode = VACUUM_MODES[mode_value]
            before = measure_sqlite_storage(connection, source)
            # A full vacuum creates a second database. SQLite's temporary files
            # and WAL activity may need additional space beyond the main file.
            if before.free_pages and mode != "full":
                required = int(
                    max(before.page_count * before.page_size, source.stat().st_size) * minimum_free_space_multiplier
                )
                if shutil.disk_usage(source.parent).free < required:
                    raise RuntimeError("insufficient free disk space for full vacuum preflight")
            checkpoint = checkpoint_wal(connection, mode="TRUNCATE")
            if checkpoint is not None and checkpoint[0]:
                raise RuntimeError("cannot compact database while WAL readers or writers prevent checkpointing")
            vacuum_performed = before.free_pages > 0 and mode != "full"
            if vacuum_performed:
                connection.execute("VACUUM")
            after = measure_sqlite_storage(connection, source)
            return CacheCompactionResult(
                journal_mode=journal_mode,
                auto_vacuum=mode,
                checkpoint_attempted=checkpoint is not None,
                checkpoint_busy=checkpoint[0] if checkpoint else None,
                checkpoint_log_pages=checkpoint[1] if checkpoint else None,
                checkpointed_pages=checkpoint[2] if checkpoint else None,
                vacuum_performed=vacuum_performed,
                before=before,
                after=after,
            )
        finally:
            _release_maintenance_lock(handle)
