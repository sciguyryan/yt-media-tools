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
