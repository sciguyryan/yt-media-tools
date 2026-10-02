"""Shared cache-migration contract and coordinator tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_media_tools.cache_migration import (
    MigrationContext,
    MigrationCoordinator,
    MigrationDestinationState,
    MigrationTransition,
    MigrationTransitionResult,
)


def _transition(
    source: int, target: int, calls: list[MigrationContext], *, complete: bool = True
) -> MigrationTransition:
    def execute(context: MigrationContext) -> MigrationTransitionResult:
        calls.append(context)
        return MigrationTransitionResult(
            source_version=source,
            target_version=target,
            destination_path=context.destination_path,
            destination_state=(
                MigrationDestinationState.COMPLETE if complete else MigrationDestinationState.INCOMPLETE
            ),
        )

    return MigrationTransition(source, target, execute)


def test_coordinator_plans_schema_chain_without_transition_details() -> None:
    calls: list[MigrationContext] = []
    v3_v4 = _transition(3, 4, calls)
    v4_v5 = _transition(4, 5, calls)
    coordinator = MigrationCoordinator((v4_v5, v3_v4))

    assert coordinator.plan(3, 5) == (v3_v4, v4_v5)
    assert calls == []


def test_coordinator_runs_each_hop_from_previous_complete_destination(tmp_path: Path) -> None:
    calls: list[MigrationContext] = []
    coordinator = MigrationCoordinator((_transition(3, 4, calls), _transition(4, 5, calls)))

    result = coordinator.run(
        tmp_path / "cache-v3.sqlite",
        lambda version: tmp_path / f"cache-v{version}.sqlite",
        source_version=3,
        target_version=5,
    )

    assert result.succeeded
    assert result.final_version == 5
    assert [call.source_path.name for call in calls] == ["cache-v3.sqlite", "cache-v4.sqlite"]
    assert [call.destination_path.name for call in calls] == ["cache-v4.sqlite", "cache-v5.sqlite"]


def test_incomplete_destination_stops_chain(tmp_path: Path) -> None:
    calls: list[MigrationContext] = []
    coordinator = MigrationCoordinator((_transition(3, 4, calls, complete=False), _transition(4, 5, calls)))

    result = coordinator.run(
        tmp_path / "cache-v3.sqlite",
        lambda version: tmp_path / f"cache-v{version}.sqlite",
        source_version=3,
        target_version=5,
    )

    assert not result.succeeded
    assert result.final_version == 4
    assert len(calls) == 1
    assert result.transitions[0].destination_state is MigrationDestinationState.INCOMPLETE


def test_coordinator_rejects_missing_hop() -> None:
    coordinator = MigrationCoordinator(())
    with pytest.raises(RuntimeError, match="no migration transition is registered from v3"):
        coordinator.plan(3, 4)


def test_coordinator_rejects_duplicate_source_transition() -> None:
    calls: list[MigrationContext] = []
    with pytest.raises(ValueError, match="multiple migration transitions start at v3"):
        MigrationCoordinator((_transition(3, 4, calls), _transition(3, 5, calls)))


def test_transition_must_advance_schema_version() -> None:
    with pytest.raises(ValueError, match="must advance"):
        MigrationTransition(4, 4, lambda context: None)  # type: ignore[arg-type]


def test_transition_result_must_match_registered_hop(tmp_path: Path) -> None:
    def execute(context: MigrationContext) -> MigrationTransitionResult:
        return MigrationTransitionResult(
            source_version=3,
            target_version=5,
            destination_path=context.destination_path,
            destination_state=MigrationDestinationState.COMPLETE,
        )

    coordinator = MigrationCoordinator((MigrationTransition(3, 4, execute),))
    with pytest.raises(RuntimeError, match="versions that do not match"):
        coordinator.run(
            tmp_path / "cache-v3.sqlite",
            lambda version: tmp_path / f"cache-v{version}.sqlite",
            source_version=3,
            target_version=4,
        )


def test_noop_chain_does_not_invent_a_transition(tmp_path: Path) -> None:
    coordinator = MigrationCoordinator(())
    result = coordinator.run(
        tmp_path / "cache-v4.sqlite",
        lambda version: tmp_path / f"cache-v{version}.sqlite",
        source_version=4,
        target_version=4,
    )
    assert result.succeeded
    assert result.transitions == ()
