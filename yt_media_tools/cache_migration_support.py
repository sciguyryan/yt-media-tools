"""Shared execution plumbing for durable metadata-cache migrations."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from typing import Any, TypeVar

from .cache_migration import MigrationContext, MigrationTransitionResult


T = TypeVar("T")


@dataclass(frozen=True)
class MigrationEvent:
    """One structured migration event suitable for progress and permanent logs."""

    occurred_at: str
    source_version: int
    target_version: int
    stage: str
    kind: str
    message: str
    completed: int | None = None
    total: int | None = None

    @classmethod
    def create(
        cls,
        context: MigrationContext,
        *,
        stage: str,
        kind: str,
        message: str,
        completed: int | None = None,
        total: int | None = None,
    ) -> "MigrationEvent":
        return cls(
            occurred_at=datetime.now(timezone.utc).isoformat(),
            source_version=context.source_version,
            target_version=context.target_version,
            stage=stage,
            kind=kind,
            message=message,
            completed=completed,
            total=total,
        )


MigrationEventSink = Callable[[MigrationEvent], None]


class MigrationEventStream:
    """Fan one event model out to any number of consumers."""

    def __init__(self, sinks: Iterable[MigrationEventSink] = ()) -> None:
        self._sinks = tuple(sinks)

    def emit(self, event: MigrationEvent) -> None:
        for sink in self._sinks:
            sink(event)


class MigrationLog:
    """Append-only JSON Lines record for one migration run."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _append(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            handle.flush()

    def event_sink(self, event: MigrationEvent) -> None:
        self._append({"record": "event", **asdict(event)})

    def start(self, context: MigrationContext) -> None:
        self._append(
            {
                "record": "start",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "source_path": str(context.source_path),
                "destination_path": str(context.destination_path),
                "source_version": context.source_version,
                "target_version": context.target_version,
            }
        )

    def finish(
        self,
        context: MigrationContext,
        *,
        status: str,
        result: MigrationTransitionResult | None = None,
        error: BaseException | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "record": "finish",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source_version": context.source_version,
            "target_version": context.target_version,
            "status": status,
        }
        if result is not None:
            payload["destination_state"] = result.destination_state.value
            payload["message"] = result.message
        if error is not None:
            payload["error_type"] = type(error).__name__
            payload["error"] = str(error)
        self._append(payload)


def run_logged_transition(
    context: MigrationContext,
    execute: Callable[[MigrationContext, MigrationEventStream], MigrationTransitionResult],
    *,
    log: MigrationLog,
    sinks: Iterable[MigrationEventSink] = (),
) -> MigrationTransitionResult:
    """Run one transition with shared events and a permanently finalised log."""
    log.start(context)
    events = MigrationEventStream((*tuple(sinks), log.event_sink))
    try:
        result = execute(context, events)
    except KeyboardInterrupt as exc:
        log.finish(context, status="interrupted", error=exc)
        raise
    except BaseException as exc:
        log.finish(context, status="failed", error=exc)
        raise
    status = "complete" if result.succeeded else "incomplete"
    log.finish(context, status=status, result=result)
    return result


def check_sqlite_integrity(connection: sqlite3.Connection) -> tuple[str, ...]:
    """Return SQLite integrity-check diagnostics; ('ok',) means success."""
    return tuple(str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall())


@dataclass(frozen=True)
class DiskSpacePreflight:
    """Observed destination storage compared with a transition's stated need."""

    path: Path
    available_bytes: int
    required_bytes: int

    @property
    def sufficient(self) -> bool:
        return self.available_bytes >= self.required_bytes


def check_disk_space(path: Path, required_bytes: int) -> DiskSpacePreflight:
    """Measure usable storage for a destination without inventing sizing policy."""
    if required_bytes < 0:
        raise ValueError("required migration disk space cannot be negative")
    probe = path if path.is_dir() else path.parent
    available = shutil.disk_usage(probe).free
    return DiskSpacePreflight(path=path, available_bytes=available, required_bytes=required_bytes)


def bounded_batches(items: Iterable[T], batch_size: int) -> Iterator[tuple[T, ...]]:
    """Yield bounded tuples while consuming the input lazily."""
    if batch_size < 1:
        raise ValueError("migration batch size must be positive")
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) == batch_size:
            yield tuple(batch)
            batch.clear()
    if batch:
        yield tuple(batch)
