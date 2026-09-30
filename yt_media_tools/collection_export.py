"""Discover export helpers for collection-interchange documents."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .collection_interchange import (
    COLLECTION_INTERCHANGE_SCHEMA,
    COLLECTION_INTERCHANGE_VERSION,
    COLLECTION_TYPE_PLAYLIST,
)
from .source_model import SourceSpec

_PLAYLIST_METADATA_FIELDS: tuple[tuple[str, str], ...] = (
    ("playlist_title", "title"),
    ("playlist_uploader", "uploader"),
    ("playlist_uploader_id", "uploader_id"),
    ("playlist_channel", "channel"),
    ("playlist_channel_id", "channel_id"),
)


def _consistent_string(records: Iterable[Mapping[str, Any]], field: str) -> str | None:
    """Return a non-empty scalar shared by all observations which provide it.

    Playlist-level metadata is repeated on yt-dlp entry dictionaries.  A disagreement
    means it is not safe to promote that value to effective collection metadata.
    """
    values = {value for record in records if isinstance((value := record.get(field)), str) and value}
    if len(values) == 1:
        return next(iter(values))
    return None


def playlist_metadata(source: SourceSpec, raw_records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Build truthful source metadata for a playlist-derived effective collection."""
    if source.kind != COLLECTION_TYPE_PLAYLIST:
        raise ValueError("collection export currently requires a playlist source")

    metadata: dict[str, str] = {}
    for raw_field, interchange_field in _PLAYLIST_METADATA_FIELDS:
        if value := _consistent_string(raw_records, raw_field):
            metadata[interchange_field] = value

    # These identify the remote playlist from which the effective collection was
    # derived.  Counts and positions are deliberately not copied from that source.
    if source.identifier:
        metadata["id"] = source.identifier
    if source.canonical_url:
        metadata["webpage_url"] = source.canonical_url
    return metadata


def collection_targets(selected_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return ordered opaque targets from a target-bearing effective query result."""
    targets: list[str] = []
    for position, row in enumerate(selected_rows, start=1):
        target = row.get("id")
        if not isinstance(target, str) or not target:
            raise ValueError(
                "collection export requires every effective query row to expose a non-empty id field; "
                f"row {position} does not"
            )
        targets.append(target)
    return targets


def build_playlist_collection(
    source: SourceSpec,
    raw_records: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
) -> dict[str, object]:
    """Build a v1 playlist collection from the effective ordered Discover result."""
    targets = collection_targets(selected_rows)
    return {
        "schema": COLLECTION_INTERCHANGE_SCHEMA,
        "version": COLLECTION_INTERCHANGE_VERSION,
        "collection": {
            "type": COLLECTION_TYPE_PLAYLIST,
            "metadata": playlist_metadata(source, raw_records),
        },
        "entries": [{"target": target} for target in targets],
    }


def write_collection(path: Path, payload: Mapping[str, object]) -> None:
    """Write one deterministic UTF-8 collection document."""
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
