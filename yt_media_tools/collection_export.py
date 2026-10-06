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
from .output import project_record
from .query import Query
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


def _collection_entry(
    row: Mapping[str, Any],
    query: Query,
    *,
    position: int,
) -> dict[str, object]:
    """Build one acquisition entry while preserving the visible yt-sql projection."""
    target = row.get("id")
    if not isinstance(target, str) or not target:
        raise ValueError(
            "collection export cannot associate every effective query row with one acquisition target; "
            f"row {position} has no retained non-empty acquisition id"
        )

    materialised = bool(query.set_operations or query.left_query is not None)
    metadata = project_record(dict(row), query.select, materialised=materialised)
    return {"target": target, "metadata": metadata}


def build_constructed_collection(
    selected_rows: Sequence[Mapping[str, Any]],
    query: Query,
) -> dict[str, object]:
    """Build a v1 effective collection without inventing remote playlist identity."""
    entries = [_collection_entry(row, query, position=position) for position, row in enumerate(selected_rows, start=1)]
    return {
        "schema": COLLECTION_INTERCHANGE_SCHEMA,
        "version": COLLECTION_INTERCHANGE_VERSION,
        "collection": {
            "type": COLLECTION_TYPE_PLAYLIST,
            "metadata": {},
        },
        "entries": entries,
    }


def build_playlist_collection(
    source: SourceSpec,
    raw_records: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
    query: Query,
) -> dict[str, object]:
    """Build a v1 playlist collection without discarding the effective projection."""
    entries = [_collection_entry(row, query, position=position) for position, row in enumerate(selected_rows, start=1)]
    return {
        "schema": COLLECTION_INTERCHANGE_SCHEMA,
        "version": COLLECTION_INTERCHANGE_VERSION,
        "collection": {
            "type": COLLECTION_TYPE_PLAYLIST,
            "metadata": playlist_metadata(source, raw_records),
        },
        "entries": entries,
    }


def write_collection(path: Path, payload: Mapping[str, object]) -> None:
    """Write one deterministic UTF-8 collection document."""
    destination = path.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
