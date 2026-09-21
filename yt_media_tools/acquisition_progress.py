"""Backend-neutral semantic progress events for Discover acquisition work.

Backends may expose implementation-specific telemetry, but the application-facing
progress contract describes semantic acquisition work. Rendering is deliberately
separate so progress can evolve without making backend details part of the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AcquisitionProgressKind(str, Enum):
    """Semantic progress event kinds emitted by acquisition orchestration."""

    STAGE_STARTED = "stage-started"
    STAGE_PROGRESS = "stage-progress"
    STAGE_COMPLETED = "stage-completed"
    ENTRY_SKIPPED = "entry-skipped"


class AcquisitionProgressStage(str, Enum):
    """Stable user-facing acquisition stages independent of a concrete backend."""

    ENUMERATION = "enumeration"
    DETAILED_METADATA = "detailed-metadata"


@dataclass(frozen=True)
class AcquisitionProgressEvent:
    """One semantic acquisition-progress observation.

    ``completed`` is the amount of work observed in the current stage. ``total`` is
    optional because streaming enumeration and some backend operations cannot know a
    trustworthy final count in advance. ``detail`` is diagnostic context and must not
    be required to understand the event's semantic meaning.
    """

    kind: AcquisitionProgressKind
    stage: AcquisitionProgressStage
    completed: int = 0
    total: int | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.completed < 0:
            raise ValueError("acquisition progress completed count cannot be negative")
        if self.total is not None:
            if self.total < 0:
                raise ValueError("acquisition progress total count cannot be negative")
            if self.completed > self.total:
                raise ValueError("acquisition progress completed count cannot exceed total")
