"""Small shared contracts for durable metadata-cache migration chains."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable


class MigrationDestinationState(str, Enum):
    """Whether a transition destination is safe to treat as finished."""

    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


@dataclass(frozen=True)
class MigrationContext:
    """Paths and versions owned by one migration hop."""

    source_path: Path
    destination_path: Path
    source_version: int
    target_version: int


@dataclass(frozen=True)
class MigrationTransitionResult:
    """Structured outcome returned by one transition implementation."""

    source_version: int
    target_version: int
    destination_path: Path
    destination_state: MigrationDestinationState
    message: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.destination_state is MigrationDestinationState.COMPLETE


MigrationExecutor = Callable[[MigrationContext], MigrationTransitionResult]


@dataclass(frozen=True)
class MigrationTransition:
    """One independently owned source-to-target schema transition."""

    source_version: int
    target_version: int
    execute: MigrationExecutor

    def __post_init__(self) -> None:
        if self.source_version < 1 or self.target_version < 1:
            raise ValueError("migration schema versions must be positive")
        if self.target_version <= self.source_version:
            raise ValueError("a migration transition must advance the schema version")


@dataclass(frozen=True)
class MigrationChainResult:
    """Result of coordinating one or more independently implemented hops."""

    initial_version: int
    requested_version: int
    transitions: tuple[MigrationTransitionResult, ...]

    @property
    def final_version(self) -> int:
        if not self.transitions:
            return self.initial_version
        return self.transitions[-1].target_version

    @property
    def succeeded(self) -> bool:
        return self.final_version == self.requested_version and all(result.succeeded for result in self.transitions)


class MigrationCoordinator:
    """Select the next migration hop without knowing how that hop transforms data."""

    def __init__(self, transitions: Iterable[MigrationTransition]) -> None:
        by_source: dict[int, MigrationTransition] = {}
        for transition in transitions:
            if transition.source_version in by_source:
                raise ValueError(f"multiple migration transitions start at v{transition.source_version}")
            by_source[transition.source_version] = transition
        self._transitions = by_source

    def plan(self, source_version: int, target_version: int) -> tuple[MigrationTransition, ...]:
        """Return the ordered hop chain required to reach target_version."""
        if source_version < 1 or target_version < 1:
            raise ValueError("migration schema versions must be positive")
        if target_version < source_version:
            raise ValueError("migration cannot move to an older schema version")
        if source_version == target_version:
            return ()

        current = source_version
        planned: list[MigrationTransition] = []
        while current < target_version:
            transition = self._transitions.get(current)
            if transition is None:
                raise RuntimeError(f"no migration transition is registered from v{current}")
            if transition.target_version > target_version:
                raise RuntimeError(
                    f"migration transition v{current}->v{transition.target_version} overshoots requested v{target_version}"
                )
            planned.append(transition)
            current = transition.target_version
        return tuple(planned)

    def run(
        self,
        source_path: Path,
        destination_for: Callable[[int], Path],
        *,
        source_version: int,
        target_version: int,
    ) -> MigrationChainResult:
        """Run planned hops, stopping as soon as a destination is incomplete."""
        planned = self.plan(source_version, target_version)
        current_path = source_path
        results: list[MigrationTransitionResult] = []

        for transition in planned:
            destination_path = destination_for(transition.target_version)
            context = MigrationContext(
                source_path=current_path,
                destination_path=destination_path,
                source_version=transition.source_version,
                target_version=transition.target_version,
            )
            result = transition.execute(context)
            self._validate_result(transition, context, result)
            results.append(result)
            if not result.succeeded:
                break
            current_path = result.destination_path

        return MigrationChainResult(
            initial_version=source_version,
            requested_version=target_version,
            transitions=tuple(results),
        )

    @staticmethod
    def _validate_result(
        transition: MigrationTransition,
        context: MigrationContext,
        result: MigrationTransitionResult,
    ) -> None:
        if (result.source_version, result.target_version) != (
            transition.source_version,
            transition.target_version,
        ):
            raise RuntimeError("migration transition returned versions that do not match its registered hop")
        if result.destination_path != context.destination_path:
            raise RuntimeError("migration transition returned an unexpected destination path")
