"""Backend source-resolution provenance contract."""

from yt_media_tools.source_resolution import (
    format_backend_resolution,
    observed_ytdlp_resolutions,
    resolution_from_ytdlp_record,
)


def test_ytdlp_resolution_preserves_raw_extractor_provenance() -> None:
    resolution = resolution_from_ytdlp_record(
        {
            "extractor": "youtube:tab",
            "extractor_key": "YoutubeTab",
            "_type": "playlist",
            "webpage_url": "https://www.youtube.com/@example/videos",
            "original_url": "https://www.youtube.com/@example",
        }
    )
    assert resolution is not None
    assert resolution.provider == "yt-dlp"
    assert resolution.extractor == "youtube:tab"
    assert resolution.extractor_key == "YoutubeTab"
    assert resolution.extractor_family == "youtube"
    assert resolution.result_type == "playlist"
    assert resolution.webpage_domain == "www.youtube.com"
    assert resolution.original_domain == "www.youtube.com"


def test_generic_extractor_does_not_claim_a_platform_family() -> None:
    resolution = resolution_from_ytdlp_record(
        {"extractor": "generic", "extractor_key": "Generic", "webpage_url": "https://example.invalid/watch"}
    )
    assert resolution is not None
    assert resolution.extractor_family is None


def test_resolution_can_be_observed_without_extractor_fields() -> None:
    resolution = resolution_from_ytdlp_record({"webpage_url_domain": "media.example"})
    assert resolution is not None
    assert resolution.extractor is None
    assert resolution.webpage_domain == "media.example"


def test_records_without_resolution_provenance_are_ignored() -> None:
    assert resolution_from_ytdlp_record({"id": "abc", "title": "Example"}) is None


def test_observed_resolutions_are_distinct_and_deterministic() -> None:
    records = [
        {"extractor": "twitch:vod", "extractor_key": "TwitchVod", "webpage_url_domain": "twitch.tv"},
        {"extractor": "youtube", "extractor_key": "Youtube", "webpage_url_domain": "www.youtube.com"},
        {"extractor": "youtube", "extractor_key": "Youtube", "webpage_url_domain": "www.youtube.com"},
    ]
    resolutions = observed_ytdlp_resolutions(records)
    assert [item.extractor for item in resolutions] == ["twitch:vod", "youtube"]


def test_human_renderer_labels_backend_facts_without_semantic_claims() -> None:
    resolution = resolution_from_ytdlp_record(
        {"extractor": "youtube", "extractor_key": "Youtube", "webpage_url_domain": "www.youtube.com"}
    )
    assert resolution is not None
    assert format_backend_resolution(resolution) == (
        "provider=yt-dlp, extractor=youtube, extractor-key=Youtube, "
        "extractor-family=youtube, result-type=video, webpage-domain=www.youtube.com"
    )


def test_single_specific_extractor_family_can_prove_physical_source_kind() -> None:
    from yt_media_tools.source_resolution import resolved_service_family

    resolutions = observed_ytdlp_resolutions(
        [
            {"extractor": "youtube:tab", "extractor_key": "YoutubeTab"},
            {"extractor": "youtube", "extractor_key": "Youtube"},
        ]
    )
    assert resolved_service_family(resolutions) == "youtube"


def test_generic_resolution_never_proves_source_kind_from_domain() -> None:
    from yt_media_tools.source_resolution import resolved_service_family

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "generic",
                "extractor_key": "Generic",
                "webpage_url": "https://www.youtube.com/watch?v=example",
                "original_url": "https://www.youtube.com/watch?v=example",
            }
        ]
    )
    assert resolved_service_family(resolutions) is None


def test_conflicting_extractor_families_remain_unresolved() -> None:
    from yt_media_tools.source_resolution import resolved_service_family

    resolutions = observed_ytdlp_resolutions(
        [
            {"extractor": "youtube", "extractor_key": "Youtube"},
            {"extractor": "twitch:vod", "extractor_key": "TwitchVod"},
        ]
    )
    assert resolved_service_family(resolutions) is None


def test_specific_and_generic_observations_remain_unresolved() -> None:
    from yt_media_tools.source_resolution import resolved_service_family

    resolutions = observed_ytdlp_resolutions(
        [
            {"extractor": "youtube", "extractor_key": "Youtube"},
            {"extractor": "generic", "extractor_key": "Generic"},
        ]
    )
    assert resolved_service_family(resolutions) is None


def test_resolved_music_origin_proves_positive_music_trait_only_after_youtube_resolution() -> None:
    from yt_media_tools.source_resolution import resolved_source_traits

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "webpage_url": "https://www.youtube.com/watch?v=example",
                "original_url": "https://music.youtube.com/watch?v=example",
            }
        ]
    )
    assert resolved_source_traits(resolutions) == frozenset({"music"})


def test_music_domain_without_specific_youtube_resolution_proves_no_music_trait() -> None:
    from yt_media_tools.source_resolution import resolved_source_traits

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "generic",
                "extractor_key": "Generic",
                "original_url": "https://music.youtube.com/watch?v=example",
            }
        ]
    )
    assert resolved_source_traits(resolutions) == frozenset()


def test_ordinary_youtube_origin_does_not_prove_negative_or_positive_music_trait() -> None:
    from yt_media_tools.source_resolution import resolved_source_traits

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "original_url": "https://www.youtube.com/watch?v=example",
            }
        ]
    )
    assert resolved_source_traits(resolutions) == frozenset()


def test_mixed_music_and_ordinary_origins_do_not_prove_batch_music_trait() -> None:
    from yt_media_tools.source_resolution import resolved_source_traits

    resolutions = observed_ytdlp_resolutions(
        [
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "original_url": "https://music.youtube.com/watch?v=music",
            },
            {
                "extractor": "youtube",
                "extractor_key": "Youtube",
                "original_url": "https://www.youtube.com/watch?v=ordinary",
            },
        ]
    )
    assert resolved_source_traits(resolutions) == frozenset()
