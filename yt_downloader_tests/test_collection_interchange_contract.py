"""Contract checks for the versioned collection interchange."""

from __future__ import annotations

import json
from pathlib import Path

from yt_media_tools.collection_interchange import (
    COLLECTION_INTERCHANGE_SCHEMA,
    COLLECTION_INTERCHANGE_VERSION,
    PLAYLIST_FIELD_CONTRACT,
    PlaylistFieldOrigin,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "collection-interchange-v1.schema.json"


def test_v1_schema_keeps_targets_backend_agnostic() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    target = schema["properties"]["entries"]["items"]["properties"]["target"]

    assert schema["properties"]["schema"]["const"] == COLLECTION_INTERCHANGE_SCHEMA
    assert schema["properties"]["version"]["const"] == COLLECTION_INTERCHANGE_VERSION
    assert target == {"type": "string", "minLength": 1}
    assert "url" not in schema["properties"]["entries"]["items"]["properties"]
    assert "id" not in schema["properties"]["entries"]["items"]["properties"]


def test_playlist_contract_covers_deliberate_yt_dlp_playlist_fields() -> None:
    fields = {item.yt_dlp_field for item in PLAYLIST_FIELD_CONTRACT}
    assert fields == {
        "n_entries",
        "playlist",
        "playlist_autonumber",
        "playlist_channel",
        "playlist_channel_id",
        "playlist_count",
        "playlist_id",
        "playlist_index",
        "playlist_title",
        "playlist_uploader",
        "playlist_uploader_id",
        "playlist_webpage_url",
    }


def test_derived_playlist_fields_are_not_stored_in_collection_metadata() -> None:
    derived = {item.yt_dlp_field for item in PLAYLIST_FIELD_CONTRACT if item.origin is PlaylistFieldOrigin.DERIVED}
    supplied = {item.interchange_key for item in PLAYLIST_FIELD_CONTRACT if item.origin is PlaylistFieldOrigin.SUPPLIED}

    assert derived == {
        "n_entries",
        "playlist",
        "playlist_autonumber",
        "playlist_count",
        "playlist_index",
    }
    assert supplied == {
        "channel",
        "channel_id",
        "id",
        "title",
        "uploader",
        "uploader_id",
        "webpage_url",
    }
