"""Cross-source reuse of entity-owned detailed metadata in cache v4."""

from yt_media_tools.cache import MetadataCache, initialise_v4_cache
from yt_media_tools.discover_acquisition import _cached_or_refresh_metadata
from yt_media_tools.ytdlp import AcquisitionStats


def test_second_source_reuses_v4_entity_metadata_without_refresh(tmp_path, monkeypatch) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    calls: list[list[str]] = []

    def fake_load(command, *, progress=None):
        video_ids = [part.rsplit("=", 1)[-1] for part in command if part.startswith("https://www.youtube.com/watch?v=")]
        calls.append(video_ids)
        return (
            [{"id": video_id, "title": f"Title {video_id}"} for video_id in video_ids],
            AcquisitionStats(available=len(video_ids)),
        )

    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)

    with MetadataCache(path) as cache:
        first, _, first_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url="https://www.youtube.com/playlist?list=FIRST",
            video_ids=["shared-video"],
            required_fields={"title"},
            verbose=0,
            cookies_file=None,
        )
        second, _, second_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url="https://www.youtube.com/playlist?list=SECOND",
            video_ids=["shared-video"],
            required_fields={"title"},
            verbose=0,
            cookies_file=None,
        )

    assert calls == [["shared-video"]]
    assert len(first) == 1
    assert first[0]["id"] == "shared-video"
    assert first[0]["title"] == "Title shared-video"
    assert len(second) == 1
    assert second[0]["id"] == "shared-video"
    assert second[0]["title"] == "Title shared-video"
    assert first_cache.misses == 1
    assert first_cache.refreshed == 1
    assert second_cache.hits == 1
    assert second_cache.refreshed == 0


def test_fresh_known_null_required_field_avoids_repeat_refresh(tmp_path, monkeypatch) -> None:
    path = tmp_path / "metadata-v4.sqlite3"
    initialise_v4_cache(path)
    calls: list[list[str]] = []

    def fake_load(command, *, progress=None):
        video_ids = [part.rsplit("=", 1)[-1] for part in command if part.startswith("https://www.youtube.com/watch?v=")]
        calls.append(video_ids)
        return (
            [{"id": video_id, "comment_count": None} for video_id in video_ids],
            AcquisitionStats(available=len(video_ids)),
        )

    monkeypatch.setattr("yt_media_tools.discover_acquisition.load_metadata", fake_load)

    with MetadataCache(path) as cache:
        first, _, first_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url="https://www.youtube.com/@example/videos",
            video_ids=["known-null-video"],
            required_fields={"comment_count"},
            verbose=0,
            cookies_file=None,
        )
        second, _, second_cache = _cached_or_refresh_metadata(
            cache=cache,
            source_url="https://www.youtube.com/@example/videos",
            video_ids=["known-null-video"],
            required_fields={"comment_count"},
            verbose=0,
            cookies_file=None,
        )

    assert calls == [["known-null-video"]]
    assert first[0]["comment_count"] is None
    assert second[0]["comment_count"] is None
    assert first_cache.misses == 1
    assert first_cache.refreshed == 1
    assert second_cache.hits == 1
    assert second_cache.refreshed == 0
