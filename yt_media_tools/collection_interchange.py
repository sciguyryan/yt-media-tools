"""Shared contract constants for the Discover-to-Downloader collection interchange.

The interchange is intentionally language-neutral.  This module records the parts of
version 1 which the Python tools need to agree on without making either tool depend
on the other's implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

COLLECTION_INTERCHANGE_SCHEMA = "yt-media-tools.collection"
COLLECTION_INTERCHANGE_VERSION = 1
COLLECTION_TYPE_PLAYLIST = "playlist"


class PlaylistFieldOrigin(str, Enum):
    """How one yt-dlp playlist field is obtained for an effective collection."""

    SUPPLIED = "supplied"
    DERIVED = "derived"


@dataclass(frozen=True)
class PlaylistFieldContract:
    """Describe one playlist field which the v1 integration deliberately supports."""

    yt_dlp_field: str
    origin: PlaylistFieldOrigin
    interchange_key: str | None = None
    notes: str = ""


# Keep this list explicit.  The collection interchange is not a generic mechanism
# for injecting arbitrary yt-dlp info-dict values.
PLAYLIST_FIELD_CONTRACT: tuple[PlaylistFieldContract, ...] = (
    PlaylistFieldContract("playlist_title", PlaylistFieldOrigin.SUPPLIED, "title"),
    PlaylistFieldContract("playlist_id", PlaylistFieldOrigin.SUPPLIED, "id"),
    PlaylistFieldContract(
        "playlist",
        PlaylistFieldOrigin.DERIVED,
        notes="playlist_title when available, otherwise playlist_id",
    ),
    PlaylistFieldContract("playlist_uploader", PlaylistFieldOrigin.SUPPLIED, "uploader"),
    PlaylistFieldContract("playlist_uploader_id", PlaylistFieldOrigin.SUPPLIED, "uploader_id"),
    PlaylistFieldContract("playlist_channel", PlaylistFieldOrigin.SUPPLIED, "channel"),
    PlaylistFieldContract("playlist_channel_id", PlaylistFieldOrigin.SUPPLIED, "channel_id"),
    PlaylistFieldContract("playlist_webpage_url", PlaylistFieldOrigin.SUPPLIED, "webpage_url"),
    PlaylistFieldContract(
        "playlist_index",
        PlaylistFieldOrigin.DERIVED,
        notes="one-based position in the effective ordered collection",
    ),
    PlaylistFieldContract(
        "playlist_autonumber",
        PlaylistFieldOrigin.DERIVED,
        notes="one-based position in the effective download queue",
    ),
    PlaylistFieldContract(
        "playlist_count",
        PlaylistFieldOrigin.DERIVED,
        notes="number of entries in the effective collection",
    ),
    PlaylistFieldContract(
        "n_entries",
        PlaylistFieldOrigin.DERIVED,
        notes="number of entries supplied by the effective collection",
    ),
)
