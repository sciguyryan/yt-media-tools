"""Contract tests for backend-neutral acquisition progress events."""

from __future__ import annotations

import pytest

from yt_media_tools.acquisition_progress import (
    AcquisitionProgressEvent,
    AcquisitionProgressKind,
    AcquisitionProgressStage,
)


def test_progress_event_supports_known_total() -> None:
    event = AcquisitionProgressEvent(
        AcquisitionProgressKind.STAGE_PROGRESS,
        AcquisitionProgressStage.DETAILED_METADATA,
        completed=25,
        total=100,
    )
    assert event.completed == 25
    assert event.total == 100


def test_progress_event_supports_unknown_total() -> None:
    event = AcquisitionProgressEvent(
        AcquisitionProgressKind.STAGE_PROGRESS,
        AcquisitionProgressStage.ENUMERATION,
        completed=100,
    )
    assert event.completed == 100
    assert event.total is None


@pytest.mark.parametrize(
    ("completed", "total"),
    [(-1, None), (0, -1), (2, 1)],
)
def test_progress_event_rejects_invalid_counts(completed: int, total: int | None) -> None:
    with pytest.raises(ValueError):
        AcquisitionProgressEvent(
            AcquisitionProgressKind.STAGE_PROGRESS,
            AcquisitionProgressStage.ENUMERATION,
            completed=completed,
            total=total,
        )
