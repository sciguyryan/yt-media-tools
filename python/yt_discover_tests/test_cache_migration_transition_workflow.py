"""Transition-owned migration workflow and failure-semantics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yt_media_tools.cache_migration import MigrationContext
from yt_media_tools.cache_migration_support import MigrationEventStream, MigrationLog, run_logged_transition
from yt_media_tools.cache_migration_workflow import (
    MigrationPhase,
    MigrationRepair,
    MigrationRepairState,
    MigrationWorkflow,
    MigrationWorkflowFailure,
    run_migration_workflow,
)


def _context(tmp_path: Path) -> MigrationContext:
    return MigrationContext(tmp_path / "v3.sqlite", tmp_path / "v4.sqlite", 3, 4)


def _workflow(
    calls: list[str],
    *,
    source=lambda context: None,
    repairs=(),
    phases=(),
    target=lambda context: None,
) -> MigrationWorkflow:
    def source_check(context: MigrationContext) -> None:
        calls.append("source")
        source(context)

    def target_check(context: MigrationContext) -> None:
        calls.append("target")
        target(context)

    return MigrationWorkflow.create(
        validate_source=source_check,
        repairs=repairs,
        phases=phases,
        validate_target=target_check,
    )


def _run_logged(tmp_path: Path, workflow: MigrationWorkflow):
    context = _context(tmp_path)
    log = MigrationLog(tmp_path / "migration.jsonl")
    result = run_logged_transition(
        context,
        lambda context, events: run_migration_workflow(context, workflow, events),
        log=log,
    )
    return result, [json.loads(line) for line in log.path.read_text().splitlines()]


def test_successful_workflow_marks_destination_complete_only_after_target_validation(tmp_path: Path) -> None:
    calls: list[str] = []
    repair = MigrationRepair(
        "legacy timestamp",
        lambda context: MigrationRepairState.APPLICABLE,
        lambda context, events: calls.append("repair"),
    )
    phase = MigrationPhase("copy metadata", lambda context, events: calls.append("phase"))
    result, records = _run_logged(tmp_path, _workflow(calls, repairs=(repair,), phases=(phase,)))
    assert result.succeeded
    assert calls == ["source", "repair", "phase", "target"]
    assert records[-1]["status"] == "complete"
    assert records[-1]["destination_state"] == "complete"


def test_source_check_failure_stops_before_repairs_and_finalises_failed_log(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(context: MigrationContext) -> None:
        raise ValueError("not a v3 source")

    with pytest.raises(MigrationWorkflowFailure, match="source validation"):
        _run_logged(tmp_path, _workflow(calls, source=fail))
    records = [json.loads(line) for line in (tmp_path / "migration.jsonl").read_text().splitlines()]
    assert calls == ["source"]
    assert records[-1]["status"] == "failed"


def test_already_applied_repair_is_reported_and_not_run(tmp_path: Path) -> None:
    calls: list[str] = []
    repair = MigrationRepair(
        "old fix",
        lambda context: MigrationRepairState.ALREADY_APPLIED,
        lambda context, events: calls.append("repair"),
    )
    _, records = _run_logged(tmp_path, _workflow(calls, repairs=(repair,)))
    assert calls == ["source", "target"]
    assert any(record.get("kind") == "skipped" and "already applied" in record.get("message", "") for record in records)


def test_repair_failure_stops_before_phases_and_target_validation(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(context: MigrationContext, events: MigrationEventStream) -> None:
        calls.append("repair")
        raise RuntimeError("repair broke")

    repair = MigrationRepair("legacy rows", lambda context: MigrationRepairState.APPLICABLE, fail)
    phase = MigrationPhase("copy", lambda context, events: calls.append("phase"))
    with pytest.raises(MigrationWorkflowFailure, match="repair legacy rows"):
        _run_logged(tmp_path, _workflow(calls, repairs=(repair,), phases=(phase,)))
    assert calls == ["source", "repair"]


def test_phase_failure_stops_before_target_validation(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(context: MigrationContext, events: MigrationEventStream) -> None:
        calls.append("phase")
        raise RuntimeError("copy broke")

    with pytest.raises(MigrationWorkflowFailure, match="phase copy"):
        _run_logged(tmp_path, _workflow(calls, phases=(MigrationPhase("copy", fail),)))
    assert calls == ["source", "phase"]


def test_target_validation_failure_cannot_mark_destination_complete(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(context: MigrationContext) -> None:
        raise RuntimeError("target invalid")

    with pytest.raises(MigrationWorkflowFailure, match="target validation"):
        _run_logged(tmp_path, _workflow(calls, target=fail))
    records = [json.loads(line) for line in (tmp_path / "migration.jsonl").read_text().splitlines()]
    assert calls == ["source", "target"]
    assert records[-1]["status"] == "failed"
    assert "destination_state" not in records[-1]


def test_interruption_during_phase_is_logged_and_propagated(tmp_path: Path) -> None:
    calls: list[str] = []

    def interrupt(context: MigrationContext, events: MigrationEventStream) -> None:
        calls.append("phase")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        _run_logged(tmp_path, _workflow(calls, phases=(MigrationPhase("copy", interrupt),)))
    records = [json.loads(line) for line in (tmp_path / "migration.jsonl").read_text().splitlines()]
    assert records[-1]["status"] == "interrupted"
    assert calls == ["source", "phase"]


def test_destination_finalisation_failure_cannot_produce_complete_result(tmp_path: Path) -> None:
    calls: list[str] = []

    def fail(context: MigrationContext) -> None:
        calls.append("finalise")
        raise RuntimeError("marker write failed")

    workflow = MigrationWorkflow.create(
        validate_source=lambda context: calls.append("source"),
        validate_target=lambda context: calls.append("target"),
        finalise_destination=fail,
    )
    with pytest.raises(MigrationWorkflowFailure, match="destination finalisation"):
        _run_logged(tmp_path, workflow)
    records = [json.loads(line) for line in (tmp_path / "migration.jsonl").read_text().splitlines()]
    assert calls == ["source", "target", "finalise"]
    assert records[-1]["status"] == "failed"
    assert "destination_state" not in records[-1]
