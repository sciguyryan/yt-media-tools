"""Explicit SQLite checkpoint and compaction operations for yt-discover caches."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sqlite3


@dataclass(frozen=True)
class SQLiteStorageMeasurement:
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


def _file_size(path: Path) -> int | None:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return None


def measure_sqlite_storage(connection: sqlite3.Connection, path: Path) -> SQLiteStorageMeasurement:
    """Measure physical SQLite allocation without changing database state."""
    path = path.expanduser()
    return SQLiteStorageMeasurement(
        page_size=int(connection.execute("PRAGMA page_size").fetchone()[0]),
        page_count=int(connection.execute("PRAGMA page_count").fetchone()[0]),
        free_pages=int(connection.execute("PRAGMA freelist_count").fetchone()[0]),
        database_bytes=_file_size(path),
        wal_bytes=_file_size(Path(str(path) + "-wal")),
    )


def compact_cache(connection: sqlite3.Connection, path: Path) -> CacheCompactionResult:
    """Explicitly checkpoint WAL where applicable and reclaim database free pages.

    The cache currently uses WAL with SQLite's default full-vacuum strategy
    (auto_vacuum=NONE). A TRUNCATE checkpoint is attempted before VACUUM so
    committed WAL content is folded into the main database and the WAL can be
    truncated when no reader prevents it. VACUUM is performed only when the
    freelist contains pages; this operation is never called implicitly by
    retention.
    """
    if connection.in_transaction:
        raise RuntimeError("cache compaction requires no active SQLite transaction")

    journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0]).lower()
    auto_vacuum_value = int(connection.execute("PRAGMA auto_vacuum").fetchone()[0])
    auto_vacuum = {0: "none", 1: "full", 2: "incremental"}.get(auto_vacuum_value, f"unknown:{auto_vacuum_value}")
    before = measure_sqlite_storage(connection, path)

    checkpoint_attempted = journal_mode == "wal"
    checkpoint_busy = checkpoint_log_pages = checkpointed_pages = None
    if checkpoint_attempted:
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        checkpoint_busy = int(checkpoint[0])
        checkpoint_log_pages = int(checkpoint[1])
        checkpointed_pages = int(checkpoint[2])
        if checkpoint_busy:
            raise RuntimeError("cannot compact metadata cache while a WAL reader or writer prevents checkpointing")

    # FULL auto-vacuum already returns freed pages at transaction commit. The
    # current cache is NONE, while INCREMENTAL would require a deliberately
    # configured incremental policy rather than an unconditional full vacuum.
    vacuum_performed = before.free_pages > 0 and auto_vacuum != "full"
    if vacuum_performed:
        connection.execute("VACUUM")

    after = measure_sqlite_storage(connection, path)
    return CacheCompactionResult(
        journal_mode=journal_mode,
        auto_vacuum=auto_vacuum,
        checkpoint_attempted=checkpoint_attempted,
        checkpoint_busy=checkpoint_busy,
        checkpoint_log_pages=checkpoint_log_pages,
        checkpointed_pages=checkpointed_pages,
        vacuum_performed=vacuum_performed,
        before=before,
        after=after,
    )
