"""Regression checks for the metadata-acquisition boundaries recorded by issue #81."""

from yt_media_tools.acquisition_plan import (
    STAGE_CATEGORIES,
    STAGE_CHAPTERS,
    STAGE_COMPLETE_METADATA,
    STAGE_DYNAMIC_RAW,
    STAGE_FORMATS,
    STAGE_SUBTITLES,
    STAGE_TAGS,
    STAGE_THUMBNAILS,
)
from yt_media_tools.source_capabilities import APPROXIMATE, EXACT, UNAVAILABLE, field_capability


def test_exact_lightweight_scalar_boundary_remains_small_and_explicit() -> None:
    for field in ("id", "title", "source_index"):
        capability = field_capability(field)
        assert capability.ytdlp_flat == EXACT
        assert not capability.requires_detailed_metadata


def test_approximate_lightweight_scalars_still_require_authoritative_detail() -> None:
    expected = {
        "upload_date": APPROXIMATE,
        "date": APPROXIMATE,
        "duration": APPROXIMATE,
        "view_count": APPROXIMATE,
        "views": APPROXIMATE,
    }
    for field, flat_quality in expected.items():
        capability = field_capability(field)
        assert capability.ytdlp_flat == flat_quality
        assert capability.ytdlp_detailed == EXACT
        assert capability.requires_detailed_metadata

    assert field_capability("duration").youtubejs == UNAVAILABLE


def test_deeper_semantic_stages_remain_distinct_before_backend_lowering() -> None:
    stages = {
        STAGE_COMPLETE_METADATA,
        STAGE_FORMATS,
        STAGE_SUBTITLES,
        STAGE_CHAPTERS,
        STAGE_THUMBNAILS,
        STAGE_TAGS,
        STAGE_CATEGORIES,
        STAGE_DYNAMIC_RAW,
    }
    assert len(stages) == 8
