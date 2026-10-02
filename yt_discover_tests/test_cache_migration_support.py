"""Shared cache-migration execution-plumbing tests."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from yt_media_tools.cache_migration import (
    MigrationContext,
    MigrationDestinationState,
    MigrationTransitionResult,
)
from yt_media_tools.cache_migration_support import (
    MigrationEvent,
    MigrationEventStream,
    MigrationLog,
    bounded_batches,
    check_disk_space,
    check_sqlite_integrity,
    run_logged_transition,
)


def _context(tmp_path: Path) -> MigrationContext:
    return MigrationContext(tmp_path / "v3.sqlite", tmp_path / "v4.sqlite", 3, 4)


def _result(context: MigrationContext, *, complete: bool = True) -> MigrationTransitionResult:
    return MigrationTransitionResult(
        source_version=3,
        target_version=4,
        destination_path=context.destination_path,
        destination_state=MigrationDestinationState.COMPLETE if complete else MigrationDestinationState.INCOMPLETE,
    )


def _records(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_event_stream_fans_same_event_to_consumers(tmp_path: Path) -> None:
    context = _context(tmp_path)
    seen_a: list[MigrationEvent] = []
    seen_b: list[MigrationEvent] = []
    event = MigrationEvent.create(context, stage="copy", kind="progress", message="Copied rows", completed=2, total=5)
    MigrationEventStream((seen_a.append, seen_b.append)).emit(event)
    assert seen_a == [event]
    assert seen_b == [event]


def test_logged_transition_uses_same_event_for_consumer_and_log(tmp_path: Path) -> None:
    context = _context(tmp_path)
    log = MigrationLog(tmp_path / "migration.jsonl")
    seen: list[MigrationEvent] = []

    def execute(context: MigrationContext, events: MigrationEventStream) -> MigrationTransitionResult:
        events.emit(
            MigrationEvent.create(context, stage="copy", kind="progress", message="Copied", completed=1, total=1)
        )
        return _result(context)

    result = run_logged_transition(context, execute, log=log, sinks=(seen.append,))
    records = _records(log.path)
    assert result.succeeded
    assert seen[0].message == "Copied"
    assert records[1]["record"] == "event"
    assert records[1]["message"] == seen[0].message
    assert records[-1]["status"] == "complete"


def test_incomplete_transition_finalises_log(tmp_path: Path) -> None:
    context = _context(tmp_path)
    log = MigrationLog(tmp_path / "migration.jsonl")
    result = run_logged_transition(context, lambda context, events: _result(context, complete=False), log=log)
    assert not result.succeeded
    assert _records(log.path)[-1]["status"] == "incomplete"


def test_failed_transition_finalises_log_and_reraises(tmp_path: Path) -> None:
    context = _context(tmp_path)
    log = MigrationLog(tmp_path / "migration.jsonl")

    def execute(context: MigrationContext, events: MigrationEventStream) -> MigrationTransitionResult:
        raise RuntimeError("copy failed")

    with pytest.raises(RuntimeError, match="copy failed"):
        run_logged_transition(context, execute, log=log)
    finish = _records(log.path)[-1]
    assert finish["status"] == "failed"
    assert finish["error_type"] == "RuntimeError"


def test_interrupted_transition_finalises_log_and_reraises(tmp_path: Path) -> None:
    context = _context(tmp_path)
    log = MigrationLog(tmp_path / "migration.jsonl")

    def execute(context: MigrationContext, events: MigrationEventStream) -> MigrationTransitionResult:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_logged_transition(context, execute, log=log)
    assert _records(log.path)[-1]["status"] == "interrupted"


def test_integrity_check_reports_healthy_database() -> None:
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE sample(value TEXT)")
    assert check_sqlite_integrity(connection) == ("ok",)
    connection.close()


def test_disk_space_preflight_reports_observation_without_policy(tmp_path: Path) -> None:
    check = check_disk_space(tmp_path / "future.sqlite", 1)
    assert check.available_bytes > 0
    assert check.required_bytes == 1
    assert check.sufficient


def test_disk_space_rejects_negative_requirement(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        check_disk_space(tmp_path, -1)


def test_bounded_batches_are_lazy_and_keep_final_partial_batch() -> None:
    consumed: list[int] = []

    def source():
        for value in range(5):
            consumed.append(value)
            yield value

    batches = bounded_batches(source(), 2)
    assert next(batches) == (0, 1)
    assert consumed == [0, 1]
    assert list(batches) == [(2, 3), (4,)]


def test_bounded_batches_require_positive_size() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        list(bounded_batches((1, 2), 0))
