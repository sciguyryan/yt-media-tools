"""Architecture guards for the #130 Part 1 raw-metadata inventory."""

from pathlib import Path

from yt_media_tools.acquisition_plan import STAGE_DYNAMIC_RAW
from yt_media_tools.schema import KNOWN_COLLECTION_TYPES, KNOWN_FIELD_TYPES


ROOT = Path(__file__).resolve().parents[1]


def test_raw_metadata_remains_an_explicit_planner_stage_during_inventory() -> None:
    assert STAGE_DYNAMIC_RAW == "dynamic-raw"


def test_stable_logical_schema_has_registered_replacement_candidates() -> None:
    assert {"id", "title", "duration", "channel_id", "view_count"} <= set(KNOWN_FIELD_TYPES)
    assert {"tags", "categories", "formats", "chapters", "thumbnails"} <= set(KNOWN_COLLECTION_TYPES)

