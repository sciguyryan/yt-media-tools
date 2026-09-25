from __future__ import annotations

from types import SimpleNamespace

from yt_media_tools.discover_acquisition import _cached_or_refresh_metadata
from yt_media_tools.provider_capabilities import MetadataRequirement
from yt_media_tools.ytdlp import AcquisitionStats


def test_ytmusicapi_production_acquisition_preserves_provenance_and_avoids_partial_cache(monkeypatch) -> None:
    import yt_media_tools.ytmusic as backend

    class FakeYTMusic:
        def get_song(self, video_id, **kwargs):
            assert kwargs["signatureTimestamp"] > 0
            return {
                "videoDetails": {"title": "Song", "channelId": "artist", "lengthSeconds": "123", "viewCount": "456"}
            }

    monkeypatch.setattr(backend.importlib, "import_module", lambda name: SimpleNamespace(YTMusic=FakeYTMusic))
    records, stats = backend.acquire_song_metadata(["abc"])
    assert stats.available == 1
    assert records == [
        {
            "id": "abc",
            "title": "Song",
            "channel_id": "artist",
            "duration": 123,
            "view_count": 456,
            "_yt_sql_metadata_provider": "ytmusicapi",
            "_yt_sql_metadata_operation": "YTMusic.get_song",
        }
    ]


def test_music_specialised_chain_uses_ytmusicapi_after_youtubejs_omission(monkeypatch, tmp_path) -> None:
    import yt_media_tools.discover_acquisition as acquisition

    monkeypatch.setattr(acquisition, "acquire_youtubejs_basic_info", lambda *args, **kwargs: ([], AcquisitionStats()))
    music_stats = AcquisitionStats(available=1)
    monkeypatch.setattr(
        acquisition,
        "acquire_ytmusic_song_metadata",
        lambda ids: (
            [
                {
                    "id": ids[0],
                    "title": "Song",
                    "channel_id": "artist",
                    "duration": 123,
                    "view_count": 456,
                    "_yt_sql_metadata_provider": "ytmusicapi",
                    "_yt_sql_metadata_operation": "YTMusic.get_song",
                }
            ],
            music_stats,
        ),
    )
    monkeypatch.setattr(
        acquisition,
        "load_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("yt-dlp should not run")),
    )
    records, stats, cache_stats = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://music.youtube.com/watch?v=abc",
        video_ids=["abc"],
        required_fields={"duration"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        specialised_fallback_providers=("ytmusicapi",),
        project_root=tmp_path,
    )
    assert records[0]["_yt_sql_metadata_provider"] == "ytmusicapi"
    assert stats.available == 1
    assert cache_stats.written == 0


def test_music_specialised_provider_chain_retains_cost_preference_then_specialised_fallback() -> None:
    from yt_media_tools.discover_application import _specialised_metadata_providers

    plan = SimpleNamespace(provider_requirements=(MetadataRequirement("complete-metadata", frozenset({"duration"})),))
    records = [
        {"extractor": "youtube", "extractor_key": "Youtube", "original_url": "https://music.youtube.com/watch?v=abc"}
    ]
    assert _specialised_metadata_providers(physical_plan=plan, resolution_records=records, cookies_file=None) == (
        "youtubejs",
        "ytmusicapi",
    )


def test_specialised_fallback_cannot_overwrite_an_entry_satisfied_by_an_earlier_provider(monkeypatch, tmp_path) -> None:
    import yt_media_tools.discover_acquisition as acquisition

    youtube_stats = AcquisitionStats(available=1)
    monkeypatch.setattr(
        acquisition,
        "acquire_youtubejs_basic_info",
        lambda *args, **kwargs: (
            [
                {
                    "id": "a",
                    "title": "YouTube.js",
                    "channel_id": "channel",
                    "duration": 1,
                    "view_count": 2,
                    "_yt_sql_metadata_provider": "youtubejs",
                    "_yt_sql_metadata_operation": "getBasicInfo",
                }
            ],
            youtube_stats,
        ),
    )

    def unexpected_music(ids):
        assert ids == ["b"]
        return (
            [
                {
                    "id": "a",
                    "title": "Conflicting",
                    "channel_id": "artist",
                    "duration": 9,
                    "view_count": 9,
                    "_yt_sql_metadata_provider": "ytmusicapi",
                    "_yt_sql_metadata_operation": "YTMusic.get_song",
                },
                {
                    "id": "b",
                    "title": "Music",
                    "channel_id": "artist",
                    "duration": 3,
                    "view_count": 4,
                    "_yt_sql_metadata_provider": "ytmusicapi",
                    "_yt_sql_metadata_operation": "YTMusic.get_song",
                },
            ],
            AcquisitionStats(available=2),
        )

    monkeypatch.setattr(acquisition, "acquire_ytmusic_song_metadata", unexpected_music)
    monkeypatch.setattr(
        acquisition,
        "load_metadata",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("yt-dlp should not run")),
    )
    records, _, _ = _cached_or_refresh_metadata(
        cache=None,
        source_url="https://music.youtube.com/playlist?list=x",
        video_ids=["a", "b"],
        required_fields={"duration"},
        verbose=0,
        cookies_file=None,
        specialised_provider="youtubejs",
        specialised_fallback_providers=("ytmusicapi",),
        project_root=tmp_path,
    )
    assert [(record["id"], record["title"], record["_yt_sql_metadata_provider"]) for record in records] == [
        ("a", "YouTube.js", "youtubejs"),
        ("b", "Music", "ytmusicapi"),
    ]


def test_metadata_provider_provenance_distinguishes_youtubejs_and_ytmusicapi() -> None:
    from yt_media_tools.discover_application import _metadata_provider_provenance

    payload = _metadata_provider_provenance(
        [
            {"id": "a", "_yt_sql_metadata_provider": "youtubejs", "_yt_sql_metadata_operation": "getBasicInfo"},
            {"id": "b", "_yt_sql_metadata_provider": "ytmusicapi", "_yt_sql_metadata_operation": "YTMusic.get_song"},
        ]
    )
    assert payload["observed"] == [
        {"provider": "youtubejs", "operation": "getBasicInfo", "records": 1},
        {"provider": "ytmusicapi", "operation": "YTMusic.get_song", "records": 1},
    ]
    assert payload["unattributed_records"] == 0
