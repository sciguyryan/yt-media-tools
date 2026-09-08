"""Source/facet grammar and capability tests for yt-sql OF."""

from __future__ import annotations

import pytest

from yt_media_tools.query import QuerySyntaxError, format_query, parse_query, query_physical_source_requests
from yt_media_tools.sources import resolve_source_request


def test_of_parses_and_formats_channel_facet() -> None:
    query = parse_query("SELECT id FROM @whatdamath OF videos")
    assert query.from_source == "@whatdamath"
    assert query.from_facet == "videos"
    assert query_physical_source_requests(query) == (("@whatdamath", "videos"),)
    assert format_query(query) == "SELECT id FROM @whatdamath OF videos"


def test_of_is_case_insensitive_but_canonicalised() -> None:
    query = parse_query("SELECT id FROM @whatdamath OF SHORTS")
    assert query.from_facet == "shorts"
    assert format_query(query) == "SELECT id FROM @whatdamath OF shorts"


def test_of_requires_a_facet_name() -> None:
    with pytest.raises(QuerySyntaxError, match="OF requires a collection/facet name"):
        parse_query("SELECT id FROM @whatdamath OF")


def test_of_survives_cte_and_union_grammar() -> None:
    query = parse_query(
        "WITH recent AS (SELECT id FROM @whatdamath OF videos) "
        "SELECT id FROM recent UNION ALL SELECT id FROM @other OF shorts"
    )
    assert query_physical_source_requests(query) == (
        ("@whatdamath", "videos"),
        ("@other", "shorts"),
    )


def test_of_rejects_cte_result_relations() -> None:
    query = parse_query("WITH x AS (SELECT id FROM @whatdamath) SELECT id FROM x OF videos")
    with pytest.raises(QuerySyntaxError, match="OF applies only to physical sources"):
        query_physical_source_requests(query)


def test_youtube_channel_facet_maps_to_existing_acquisition_surface() -> None:
    spec = resolve_source_request("@whatdamath", facet="live")
    assert spec.kind == "channel"
    assert spec.facet == "live"
    assert spec.canonical_url.endswith("/streams")


def test_playlist_rejects_channel_facet() -> None:
    with pytest.raises(ValueError, match="does not advertise facet"):
        resolve_source_request("PL1234567890", facet="videos")


def test_generic_extractor_rejects_unadvertised_facet() -> None:
    with pytest.raises(ValueError, match="does not advertise facet"):
        resolve_source_request("https://www.twitch.tv/example/videos", facet="videos")


def test_of_and_tab_share_one_compatibility_model() -> None:
    spec = resolve_source_request("@whatdamath", facet="videos", tab="videos")
    assert spec.facet == "videos"
    with pytest.raises(ValueError, match="conflicts"):
        resolve_source_request("@whatdamath", facet="shorts", tab="videos")


def test_same_physical_source_multiple_facets_fails_closed_for_initial_foundation() -> None:
    query = parse_query("SELECT id FROM @whatdamath OF videos UNION ALL SELECT id FROM @whatdamath OF shorts")
    with pytest.raises(QuerySyntaxError, match="multiple facets"):
        query_physical_source_requests(query)


def test_repeated_same_source_and_facet_is_one_physical_request() -> None:
    query = parse_query("SELECT id FROM @whatdamath OF videos UNION ALL SELECT id FROM @whatdamath OF videos")
    assert query_physical_source_requests(query) == (("@whatdamath", "videos"),)


def test_source_capabilities_are_adapter_scoped_and_deterministic() -> None:
    from yt_media_tools.sources import resolve_source, source_capabilities

    channel = source_capabilities(resolve_source("@whatdamath"))
    playlist = source_capabilities(resolve_source("PL1234567890"))
    generic = source_capabilities(resolve_source("https://www.twitch.tv/example/videos"))

    assert channel.adapter == "youtube-channel"
    assert channel.facets == ("videos", "shorts", "live")
    assert playlist.adapter == "youtube-playlist"
    assert playlist.facets == ()
    assert generic.adapter == "yt-dlp-generic"
    assert generic.facets == ()


def test_legacy_tab_is_materialised_as_the_same_logical_facet() -> None:
    from yt_media_tools.sources import resolve_source

    legacy = resolve_source("@whatdamath", tab="shorts")
    modern = resolve_source_request("@whatdamath", facet="shorts")
    assert legacy == modern
    assert legacy.facet == "shorts"


def test_capability_diagnostic_names_adapter_and_advertised_facets() -> None:
    with pytest.raises(ValueError, match="adapter 'youtube-playlist' advertises: none"):
        resolve_source_request("PL1234567890", facet="videos")


def test_channel_unknown_facet_lists_supported_facets() -> None:
    with pytest.raises(ValueError, match="adapter 'youtube-channel' advertises: videos, shorts, live"):
        resolve_source_request("@whatdamath", facet="archives")
