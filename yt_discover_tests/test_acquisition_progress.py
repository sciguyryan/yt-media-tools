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


def test_renderer_reports_known_stage_transition_and_progress() -> None:
    from io import StringIO

    from yt_media_tools.acquisition_progress import render_acquisition_progress

    stream = StringIO()
    for event in (
        AcquisitionProgressEvent(
            AcquisitionProgressKind.STAGE_STARTED,
            AcquisitionProgressStage.DETAILED_METADATA,
            total=50,
        ),
        AcquisitionProgressEvent(
            AcquisitionProgressKind.STAGE_PROGRESS,
            AcquisitionProgressStage.DETAILED_METADATA,
            completed=25,
            total=50,
        ),
        AcquisitionProgressEvent(
            AcquisitionProgressKind.STAGE_COMPLETED,
            AcquisitionProgressStage.DETAILED_METADATA,
            completed=50,
            total=50,
        ),
    ):
        render_acquisition_progress(event, stream=stream)

    assert stream.getvalue().splitlines() == [
        "yt-discover: Detailed metadata: started for 50 candidates.",
        "yt-discover: Detailed metadata: 25/50 complete.",
        "yt-discover: Detailed metadata: complete (50/50).",
    ]


def test_renderer_degrades_cleanly_when_total_is_unknown() -> None:
    from io import StringIO

    from yt_media_tools.acquisition_progress import render_acquisition_progress

    stream = StringIO()
    render_acquisition_progress(
        AcquisitionProgressEvent(
            AcquisitionProgressKind.STAGE_PROGRESS,
            AcquisitionProgressStage.DETAILED_METADATA,
            completed=25,
        ),
        stream=stream,
    )
    assert stream.getvalue() == "yt-discover: Detailed metadata: 25 observed so far.\n"
