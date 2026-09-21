"""Backend-neutral semantic progress events and rendering for Discover acquisition work.

Backends may expose implementation-specific telemetry, but the application-facing
progress contract describes semantic acquisition work. Rendering is deliberately
separate so progress can evolve without making backend details part of the UI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import TextIO


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
    """One semantic acquisition-progress observation."""

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


def render_acquisition_progress(event: AcquisitionProgressEvent, *, stream: TextIO | None = None) -> None:
    """Render one concise semantic acquisition event to the diagnostic stream."""
    output = stream if stream is not None else sys.stderr
    stage = {
        AcquisitionProgressStage.ENUMERATION: "Source enumeration",
        AcquisitionProgressStage.DETAILED_METADATA: "Detailed metadata",
    }[event.stage]
    if event.kind is AcquisitionProgressKind.STAGE_STARTED:
        suffix = f" for {event.total} candidates" if event.total is not None else ""
        message = f"{stage}: started{suffix}."
    elif event.kind is AcquisitionProgressKind.STAGE_COMPLETED:
        if event.total is not None:
            message = f"{stage}: complete ({event.completed}/{event.total})."
        else:
            message = f"{stage}: complete ({event.completed} observed)."
    elif event.kind is AcquisitionProgressKind.STAGE_PROGRESS:
        if event.total is not None:
            message = f"{stage}: {event.completed}/{event.total} complete."
        else:
            message = f"{stage}: {event.completed} observed so far."
    else:
        message = f"{stage}: skipped inaccessible entry"
        if event.detail:
            message += f": {event.detail}"
        message += "."
    print(f"yt-discover: {message}", file=output, flush=True)
