"""Registered cache-v4 metadata contract for the yt-dlp provider."""

from __future__ import annotations

from typing import Any, Mapping

from .cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from .query_types import QueryType


_STABLE_SCALARS: tuple[tuple[str, str, FreshnessPolicy], ...] = (
    ("id", "string", FreshnessPolicy.immutable()),
    ("title", "string", FreshnessPolicy.max_age(7 * 86400)),
    ("upload_date", "date", FreshnessPolicy.immutable()),
    ("duration", "duration", FreshnessPolicy.max_age(30 * 86400)),
    ("view_count", "count", FreshnessPolicy.max_age(6 * 3600)),
    ("like_count", "count", FreshnessPolicy.max_age(6 * 3600)),
    ("comment_count", "count", FreshnessPolicy.max_age(6 * 3600)),
    ("channel_follower_count", "count", FreshnessPolicy.max_age(6 * 3600)),
    ("uploader", "string", FreshnessPolicy.max_age(7 * 86400)),
    ("uploader_id", "string", FreshnessPolicy.immutable()),
    ("channel", "string", FreshnessPolicy.max_age(7 * 86400)),
    ("channel_id", "string", FreshnessPolicy.immutable()),
    ("live_status", "string", FreshnessPolicy.max_age(3600)),
    ("availability", "string", FreshnessPolicy.max_age(3600)),
    ("is_live", "boolean", FreshnessPolicy.max_age(3600)),
    ("was_live", "boolean", FreshnessPolicy.max_age(3600)),
    ("webpage_url", "string", FreshnessPolicy.max_age(30 * 86400)),
    ("playlist_id", "string", FreshnessPolicy.max_age(30 * 86400)),
    ("playlist_title", "string", FreshnessPolicy.max_age(30 * 86400)),
    ("timestamp", "datetime", FreshnessPolicy.immutable()),
    ("release_timestamp", "datetime", FreshnessPolicy.immutable()),
    ("modified_timestamp", "datetime", FreshnessPolicy.max_age(86400)),
)

# These fields already have a stable language-level representation but are not scalar
# cache-v4 columns yet. Part 2 accounts for them explicitly instead of pretending they
# were normalised or treating them as unexplained discarded backend baggage.
STABLE_COLLECTION_EQUIVALENTS = frozenset({"tags", "categories", "formats", "chapters", "thumbnails"})

YTDLP_PROVIDER = ProviderDefinition(
    key="yt-dlp",
    schema_revision=1,
    metadata_table="cache_v4_ytdlp_metadata",
    acquisition_groups=(AcquisitionGroupDefinition("detailed"),),
    fields=tuple(
        ProviderFieldDefinition(
            name=name,
            value_type=QueryType.scalar(kind, nullable=True),
            acquisition_group="detailed",
            storage_name=name,
            freshness=freshness,
        )
        for name, kind, freshness in _STABLE_SCALARS
    ),
    applicability=ProviderApplicability(services=frozenset({"youtube"})),
)


def normalise_registered_metadata(
    record: Mapping[str, Any],
) -> dict[str, object | None]:
    """Extract the registered scalar values represented by one backend record."""
    registered: dict[str, object | None] = {}
    for field in YTDLP_PROVIDER.fields:
        value = record.get(field.name)
        if value is None or isinstance(value, (str, int, float, bool)):
            registered[field.name] = value

    return registered
