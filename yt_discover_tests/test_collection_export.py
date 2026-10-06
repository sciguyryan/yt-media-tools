from __future__ import annotations

import json

import pytest

from yt_media_tools.collection_export import build_playlist_collection, write_collection
from yt_media_tools.query import Query, SelectTerm
from yt_media_tools.query_model import Literal, ScalarBinary
from yt_media_tools.source_model import SourceSpec


def _playlist() -> SourceSpec:
    return SourceSpec(
        "playlist",
        "PLexample123",
        "https://www.youtube.com/playlist?list=PLexample123",
        "PLexample123",
    )


def _query(*terms: SelectTerm) -> Query:
    return Query(select=terms)


def test_collection_export_preserves_effective_projection_and_hidden_target(tmp_path):
    raw = [
        {"id": "a", "title": "Alpha", "duration": 0, "description": None, "playlist_title": "Original"},
        {"id": "c", "title": "Charlie", "duration": 42, "description": None, "playlist_title": "Original"},
    ]
    selected = [raw[1], raw[0]]
    query = _query(
        SelectTerm("title", "name", kind="string"),
        SelectTerm("duration", "duration", kind="number"),
        SelectTerm("description", "description", kind="string"),
    )

    payload = build_playlist_collection(_playlist(), raw, selected, query)

    assert payload["entries"] == [
        {"target": "c", "metadata": {"name": "Charlie", "duration": 42, "description": None}},
        {"target": "a", "metadata": {"name": "Alpha", "duration": 0, "description": None}},
    ]
    assert payload["collection"]["metadata"]["title"] == "Original"

    destination = tmp_path / "nested" / "collection.json"
    write_collection(destination, payload)
    assert json.loads(destination.read_text(encoding="utf-8")) == payload


def test_collection_export_preserves_aliases_calculations_null_and_falsey_values():
    row = {"id": "a", "title": "", "duration": 120, "view_count": 0, "is_live": False}
    query = _query(
        SelectTerm("title", "empty_title", kind="string"),
        SelectTerm("view_count", "views", kind="number"),
        SelectTerm("is_live", "live", kind="boolean"),
        SelectTerm(
            "minutes",
            "minutes",
            expression=ScalarBinary("/", Literal(120, "120"), Literal(60, "60")),
        ),
    )

    payload = build_playlist_collection(_playlist(), [row], [row], query)

    assert payload["entries"][0] == {
        "target": "a",
        "metadata": {"empty_title": "", "views": 0, "live": False, "minutes": 2.0},
    }


def test_collection_export_duplicate_targets_keep_independent_projected_rows():
    first = {"id": "same", "title": "First"}
    second = {"id": "same", "title": "Second"}
    query = _query(SelectTerm("title", "label", kind="string"))

    payload = build_playlist_collection(_playlist(), [first, second], [first, second], query)

    assert payload["entries"] == [
        {"target": "same", "metadata": {"label": "First"}},
        {"target": "same", "metadata": {"label": "Second"}},
    ]


def test_collection_export_rejects_materialised_row_without_acquisition_identity():
    query = _query(SelectTerm("title", "title", kind="string"))

    with pytest.raises(ValueError, match="acquisition target"):
        build_playlist_collection(_playlist(), [], [{"title": "Projected only"}], query)


def test_collection_export_rejects_non_playlist_source():
    source = SourceSpec("channel", "UCexample123", "https://www.youtube.com/@example", "UCexample123")
    query = _query(SelectTerm("id", "id", kind="string"))

    with pytest.raises(ValueError, match="playlist source"):
        build_playlist_collection(source, [], [{"id": "a"}], query)


def test_constructed_collection_preserves_hidden_target_and_projected_expression():
    from yt_media_tools.collection_export import build_constructed_collection
    from yt_media_tools.query import parse_query

    query = parse_query("SELECT CONCAT(id, ' # ', title) FROM source")
    selected = [{"id": "abc123", "title": "Example"}]

    payload = build_constructed_collection(selected, query)

    assert payload["collection"] == {"type": "playlist", "metadata": {}}
    assert payload["entries"] == [
        {
            "target": "abc123",
            "metadata": {"CONCAT(id, ' # ', title)": "abc123 # Example"},
        }
    ]
