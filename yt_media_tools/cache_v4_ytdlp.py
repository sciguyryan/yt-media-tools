"""Registered cache-v4 metadata contract for the yt-dlp provider."""

from __future__ import annotations

from typing import Any, Mapping

from .cache_registry import (
    AcquisitionGroupDefinition,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from .freshness_config import BUILTIN_FRESHNESS_CONFIG, load_freshness_configuration
from .query_types import QueryType


_STABLE_SCALARS: tuple[tuple[str, str], ...] = (
    ("id", "string"),
    ("title", "string"),
    ("upload_date", "date"),
    ("duration", "duration"),
    ("view_count", "count"),
    ("like_count", "count"),
    ("comment_count", "count"),
    ("channel_follower_count", "count"),
    ("uploader", "string"),
    ("uploader_id", "string"),
    ("channel", "string"),
    ("channel_id", "string"),
    ("live_status", "string"),
    ("availability", "string"),
    ("is_live", "boolean"),
    ("was_live", "boolean"),
    ("webpage_url", "string"),
    ("playlist_id", "string"),
    ("playlist_title", "string"),
    ("timestamp", "datetime"),
    ("release_timestamp", "datetime"),
    ("modified_timestamp", "datetime"),
)
YTDLP_FRESHNESS_FIELDS = tuple(name for name, _kind in _STABLE_SCALARS)

YTDLP_FRESHNESS_POLICIES = load_freshness_configuration(
    BUILTIN_FRESHNESS_CONFIG,
    origin="built-in",
    provider_fields={"yt-dlp": YTDLP_FRESHNESS_FIELDS},
    require_complete=True,
).provider("yt-dlp")
assert YTDLP_FRESHNESS_POLICIES is not None
_YTDLP_FIELD_FRESHNESS = dict(YTDLP_FRESHNESS_POLICIES.fields)

# These fields already have a stable language-level representation but are not scalar
# cache-v4 columns yet. Part 2 accounts for them explicitly instead of pretending they
# were normalised or treating them as unexplained discarded backend baggage.
STABLE_COLLECTION_EQUIVALENTS = frozenset({"tags", "categories", "formats", "chapters", "thumbnails"})

YTDLP_PROVIDER = ProviderDefinition(
    key="yt-dlp",
    schema_revision=2,
    metadata_table="cache_v4_ytdlp_metadata",
    acquisition_groups=(AcquisitionGroupDefinition("detailed"),),
    fields=tuple(
        ProviderFieldDefinition(
            name=name,
            value_type=QueryType.scalar(kind, nullable=True),
            acquisition_group="detailed",
            storage_name=name,
            freshness=_YTDLP_FIELD_FRESHNESS[name].policy,
        )
        for name, kind in _STABLE_SCALARS
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
