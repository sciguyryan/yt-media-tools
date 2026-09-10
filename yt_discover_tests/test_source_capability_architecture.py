"""Architectural tests for stable source, facet and capability declarations."""

from __future__ import annotations

from yt_media_tools.capabilities import EXACT, UNAVAILABLE, field_capability
from yt_media_tools.source_capabilities import (
    STRUCTURALLY_SUPPORTED,
    STRUCTURALLY_UNSUPPORTED,
    STRUCTURAL_SUPPORT_UNKNOWN,
    FacetCapabilities,
    FieldCapability,
)
from yt_media_tools.sources import (
    LogicalSourceIdentity,
    PhysicalSourceIdentity,
    SourceSpec,
    logical_source_identity,
    resolve_source,
    resolve_source_request,
    selected_facet_capabilities,
    source_capabilities,
)


def test_sources_module_preserves_model_compatibility_exports() -> None:
    assert SourceSpec.__module__ == "yt_media_tools.source_model"
    assert PhysicalSourceIdentity.__module__ == "yt_media_tools.source_model"
    assert LogicalSourceIdentity.__module__ == "yt_media_tools.source_model"


def test_channel_declares_default_and_named_logical_collections() -> None:
    source = resolve_source("@whatdamath")
    capabilities = source_capabilities(source)

    assert capabilities.adapter == "youtube-channel"
    assert capabilities.facets == ("videos", "shorts", "live")
    assert capabilities.facet_capabilities().name is None
    assert [capabilities.facet_capabilities(name).name for name in capabilities.facets] == [
        "videos",
        "shorts",
        "live",
    ]


def test_selected_channel_facet_has_stable_schema_and_acquisition_facts() -> None:
    source = resolve_source_request("@whatdamath", facet="shorts")
    facet = selected_facet_capabilities(source)
    fields = {field.name: field for field in facet.logical_schema}

    assert facet.name == "shorts"
    assert facet.stable_collection
    assert facet.trustworthy_order_field == "source_index"
    assert facet.cheaply_enumerates_identities
    assert fields["id"].kind == "string"
    assert not fields["id"].nullable
    assert fields["duration"].kind == "duration"


def test_playlist_and_generic_extractors_have_distinct_adapter_contracts() -> None:
    playlist = source_capabilities(resolve_source("PL1234567890"))
    generic = source_capabilities(resolve_source("https://www.twitch.tv/example/videos"))

    assert playlist.adapter == "youtube-playlist"
    assert playlist.facet_capabilities().stable_collection
    assert generic.adapter == "yt-dlp-generic"
    assert not generic.facet_capabilities().stable_collection
    assert generic.facet_capabilities().trustworthy_order_field is None
    assert not generic.facet_capabilities().cheaply_enumerates_identities
    assert playlist.facets == generic.facets == ()


def test_logical_facet_identity_preserves_one_physical_channel_identity() -> None:
    videos = logical_source_identity(resolve_source_request("@whatdamath", facet="videos"))
    shorts = logical_source_identity(resolve_source_request("@whatdamath", facet="shorts"))

    assert videos.physical == shorts.physical
    assert videos.canonical_url != shorts.canonical_url
    assert videos.cache_key != shorts.cache_key
    assert videos.provenance_key != shorts.provenance_key


def test_dynamic_field_capability_is_unknown_not_structurally_unsupported() -> None:
    capability = field_capability("raw.extra.score")

    assert capability.ytdlp_flat == UNAVAILABLE
    assert capability.ytdlp_detailed == EXACT
    assert capability.logical_kind is None
    assert capability.structural_support == STRUCTURAL_SUPPORT_UNKNOWN


def test_facet_contract_can_declare_a_field_structurally_unsupported() -> None:
    unsupported = FieldCapability(
        "duration",
        UNAVAILABLE,
        UNAVAILABLE,
        UNAVAILABLE,
        logical_kind="duration",
        structural_support=STRUCTURALLY_UNSUPPORTED,
    )
    facet = FacetCapabilities(
        name="fixture",
        logical_schema=(),
        stable_collection=True,
        trustworthy_order_field=None,
        cheaply_enumerates_identities=False,
        field_overrides=(unsupported,),
    )

    assert facet.field("duration") == unsupported
    assert facet.field("duration").structural_support == STRUCTURALLY_UNSUPPORTED


def test_known_detailed_only_field_keeps_stable_logical_kind() -> None:
    capability = field_capability("like_count")

    assert capability.ytdlp_flat == UNAVAILABLE
    assert capability.ytdlp_detailed == EXACT
    assert capability.logical_kind == "count"
    assert capability.structural_support == STRUCTURALLY_SUPPORTED
