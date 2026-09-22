"""Current source-resolution boundaries recorded by issue #81 Phase 4."""

from yt_media_tools.query_evaluator import _stable_random_identity
from yt_media_tools.source_capabilities import source_capabilities
from yt_media_tools.source_model import SourceSpec


def test_extractor_identity_participates_in_metadata_identity_fallback() -> None:
    """yt-dlp extractor provenance is already recognised when stronger IDs are absent."""
    record = {"extractor": "example", "extractor_key": "ExampleIE"}
    assert '["extractor","example"]' in _stable_random_identity(record)


def test_extractor_key_is_retained_as_identity_fallback() -> None:
    """The backend extractor key remains observable provenance rather than being discarded."""
    record = {"extractor_key": "ExampleIE"}
    assert '["extractor_key","ExampleIE"]' in _stable_random_identity(record)


def test_generic_source_does_not_inherit_youtube_capabilities_from_url_shape() -> None:
    """Provider-specific capability selection must follow resolved source identity, not URL appearance."""
    source = SourceSpec("extractor", "https://www.youtube.com/example", "https://www.youtube.com/example", None)
    capabilities = source_capabilities(source)
    assert capabilities.adapter == "yt-dlp-generic"
    assert not capabilities.facet_capabilities().cheaply_enumerates_identities
