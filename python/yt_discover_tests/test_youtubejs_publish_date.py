"""Independent publication-date metadata contract."""

from yt_media_tools.schema import KNOWN_FIELD_TYPES
from yt_media_tools.provider_capabilities import YOUTUBEJS_EXACT_SCALAR_FIELDS
from yt_media_tools.youtubejs import _basic_info_upload_date


def test_publish_date_is_independent_registered_calendar_field():
    assert KNOWN_FIELD_TYPES["publish_date"] == "date"
    assert "publish_date" in YOUTUBEJS_EXACT_SCALAR_FIELDS
    assert _basic_info_upload_date("2024-02-29") == "20240229"
    assert _basic_info_upload_date("2026-02-29") is None
