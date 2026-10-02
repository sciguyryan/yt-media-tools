"""Transition-owned workflow for durable metadata-cache migrations."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum

from .cache_migration import (
    MigrationContext,
    MigrationDestinationState,
    MigrationTransitionResult,
)
from .cache_migration_support import MigrationEvent, MigrationEventStream


ValidationCheck = Callable[[MigrationContext], None]
MigrationPhaseAction = Callable[[MigrationContext, MigrationEventStream], None]


class MigrationRepairState(str, Enum):
    """Whether a historical repair still needs to run."""

    APPLICABLE = "applicable"
    ALREADY_APPLIED = "already_applied"


RepairCheck = Callable[[MigrationContext], MigrationRepairState]
RepairAction = Callable[[MigrationContext, MigrationEventStream], None]


@dataclass(frozen=True)
class MigrationRepair:
    """One transition-owned historical repair and its applicability check."""

    name: str
    check: RepairCheck
    apply: RepairAction


@dataclass(frozen=True)
class MigrationPhase:
    """One named transformation phase owned by a schema transition."""

    name: str
    run: MigrationPhaseAction


@dataclass(frozen=True)
class MigrationWorkflow:
    """The ordered work performed by one source-to-target transition."""

    validate_source: ValidationCheck
    repairs: tuple[MigrationRepair, ...]
    phases: tuple[MigrationPhase, ...]
    validate_target: ValidationCheck

    @classmethod
    def create(
        cls,
        *,
        validate_source: ValidationCheck,
        repairs: Iterable[MigrationRepair] = (),
        phases: Iterable[MigrationPhase] = (),
        validate_target: ValidationCheck,
    ) -> "MigrationWorkflow":
        return cls(
            validate_source=validate_source,
            repairs=tuple(repairs),
            phases=tuple(phases),
            validate_target=validate_target,
        )


class MigrationWorkflowFailure(RuntimeError):
    """A workflow stage failed and left the destination incomplete."""

    def __init__(self, stage: str, cause: BaseException) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"migration {stage} failed: {cause}")


def _emit(
    context: MigrationContext,
    events: MigrationEventStream,
    *,
    stage: str,
    kind: str,
    message: str,
) -> None:
    events.emit(MigrationEvent.create(context, stage=stage, kind=kind, message=message))


def _run_stage(
    context: MigrationContext,
    events: MigrationEventStream,
    *,
    stage: str,
    action: Callable[[], None],
) -> None:
    _emit(context, events, stage=stage, kind="start", message=f"Starting {stage}")
    try:
        action()
    except KeyboardInterrupt:
        _emit(context, events, stage=stage, kind="interrupted", message=f"Interrupted {stage}")
        raise
    except BaseException as exc:
        _emit(context, events, stage=stage, kind="failed", message=f"Failed {stage}: {exc}")
        raise MigrationWorkflowFailure(stage, exc) from exc
    _emit(context, events, stage=stage, kind="complete", message=f"Completed {stage}")


def run_migration_workflow(
    context: MigrationContext,
    workflow: MigrationWorkflow,
    events: MigrationEventStream,
) -> MigrationTransitionResult:
    """Run one transition workflow; only target validation can mark it complete."""
    _run_stage(
        context,
        events,
        stage="source validation",
        action=lambda: workflow.validate_source(context),
    )

    for repair in workflow.repairs:
        stage = f"repair {repair.name}"
        try:
            state = repair.check(context)
        except KeyboardInterrupt:
            _emit(context, events, stage=stage, kind="interrupted", message=f"Interrupted {stage} check")
            raise
        except BaseException as exc:
            _emit(context, events, stage=stage, kind="failed", message=f"Failed {stage} check: {exc}")
            raise MigrationWorkflowFailure(f"{stage} check", exc) from exc

        if state is MigrationRepairState.ALREADY_APPLIED:
            _emit(context, events, stage=stage, kind="skipped", message=f"Skipped {stage}: already applied")
            continue
        if state is not MigrationRepairState.APPLICABLE:
            raise RuntimeError(f"repair {repair.name} returned an unknown state: {state!r}")

        _run_stage(
            context,
            events,
            stage=stage,
            action=lambda repair=repair: repair.apply(context, events),
        )

    for phase in workflow.phases:
        _run_stage(
            context,
            events,
            stage=f"phase {phase.name}",
            action=lambda phase=phase: phase.run(context, events),
        )

    _run_stage(
        context,
        events,
        stage="target validation",
        action=lambda: workflow.validate_target(context),
    )
    return MigrationTransitionResult(
        source_version=context.source_version,
        target_version=context.target_version,
        destination_path=context.destination_path,
        destination_state=MigrationDestinationState.COMPLETE,
    )
