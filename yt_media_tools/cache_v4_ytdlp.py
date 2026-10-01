"""Registered cache-v4 metadata contract for the yt-dlp provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .cache_registry import (
    AcquisitionGroupDefinition,
    FreshnessPolicy,
    ProviderApplicability,
    ProviderDefinition,
    ProviderFieldDefinition,
)
from .query_types import QueryType


@dataclass(frozen=True)
class RawMigrationAccounting:
    """Explain how one legacy backend record maps onto registered v4 metadata."""

    registered_fields: tuple[str, ...]
    stable_equivalent_fields: tuple[str, ...]
    discarded_backend_fields: tuple[str, ...]

    @property
    def recognised_count(self) -> int:
        return len(self.registered_fields) + len(self.stable_equivalent_fields)

    @property
    def discarded_count(self) -> int:
        return len(self.discarded_backend_fields)


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
) -> tuple[dict[str, object | None], RawMigrationAccounting]:
    """Split one backend record into registered scalar values and explicit remainder."""
    registered: dict[str, object | None] = {}
    for field in YTDLP_PROVIDER.fields:
        value = record.get(field.name)
        if value is None or isinstance(value, (str, int, float, bool)):
            registered[field.name] = value

    stable_equivalent = tuple(sorted(name for name in STABLE_COLLECTION_EQUIVALENTS if name in record))
    accounted = set(registered) | set(stable_equivalent)
    discarded = tuple(
        sorted(
            key for key in record if isinstance(key, str) and key not in accounted and not key.startswith("_yt_sql_")
        )
    )
    return registered, RawMigrationAccounting(
        registered_fields=tuple(sorted(registered)),
        stable_equivalent_fields=stable_equivalent,
        discarded_backend_fields=discarded,
    )
