from __future__ import annotations

import json

import pytest

from yt_media_tools.collection_export import build_playlist_collection, write_collection
from yt_media_tools.source_model import SourceSpec


def _playlist() -> SourceSpec:
    return SourceSpec(
        "playlist",
        "PLexample123",
        "https://www.youtube.com/playlist?list=PLexample123",
        "PLexample123",
    )


def test_collection_export_uses_effective_result_order_and_count(tmp_path):
    raw = [
        {"id": "a", "playlist_title": "Original", "playlist_count": 99},
        {"id": "b", "playlist_title": "Original", "playlist_count": 99},
        {"id": "c", "playlist_title": "Original", "playlist_count": 99},
    ]
    selected = [{"id": "c"}, {"id": "a"}]

    payload = build_playlist_collection(_playlist(), raw, selected)

    assert payload["entries"] == [{"target": "c"}, {"target": "a"}]
    assert payload["collection"]["metadata"] == {
        "id": "PLexample123",
        "title": "Original",
        "webpage_url": "https://www.youtube.com/playlist?list=PLexample123",
    }
    assert "playlist_count" not in payload["collection"]["metadata"]

    destination = tmp_path / "nested" / "collection.json"
    write_collection(destination, payload)
    assert json.loads(destination.read_text(encoding="utf-8")) == payload


def test_collection_export_keeps_only_consistent_repeated_playlist_metadata():
    raw = [
        {"id": "a", "playlist_title": "Original", "playlist_uploader": "Owner"},
        {"id": "b", "playlist_title": "Original", "playlist_uploader": "Different"},
    ]

    payload = build_playlist_collection(_playlist(), raw, [{"id": "a"}])

    metadata = payload["collection"]["metadata"]
    assert metadata["title"] == "Original"
    assert "uploader" not in metadata


def test_collection_export_rejects_non_target_result_rows():
    with pytest.raises(ValueError, match="row 1"):
        build_playlist_collection(_playlist(), [], [{"title": "Projected only"}])


def test_collection_export_rejects_non_playlist_source():
    source = SourceSpec("channel", "UCexample123", "https://www.youtube.com/@example", "UCexample123")
    with pytest.raises(ValueError, match="playlist source"):
        build_playlist_collection(source, [], [{"id": "a"}])
