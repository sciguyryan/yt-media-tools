"""Collection-state foundation tests."""

import sqlite3

import pytest

from yt_media_tools.collection_state import CollectionState, CollectionStateError, resolve_collection_identity


def test_membership_reopen_and_cleanup(tmp_path):
    state = CollectionState(tmp_path)
    state.record("youtube-playlist:A", "first")
    state.record("youtube-playlist:A", "first")
    state.record("youtube-playlist:B", "second")
    assert CollectionState(tmp_path).completed("youtube-playlist:A") == {"first"}
    state.clear("youtube-playlist:A")
    assert state.completed("youtube-playlist:A") == set()
    assert state.completed("youtube-playlist:B") == {"second"}


def test_unsupported_schema_preserves_data(tmp_path):
    state = CollectionState(tmp_path)
    state.record("youtube-playlist:A", "first")
    with sqlite3.connect(state.path) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(CollectionStateError, match="unsupported"):
        state.completed("youtube-playlist:A")


def test_identity_requires_explicit_provenance():
    metadata = {"id": "PL123", "webpage_url": "https://www.youtube.com/playlist?list=PL123"}
    assert resolve_collection_identity({"metadata": metadata}) is None
    assert (
        resolve_collection_identity({"metadata": metadata, "identity_kind": "native-playlist"})
        == "youtube-playlist:PL123"
    )
    assert (
        resolve_collection_identity({"identity": "collection-uuid:550e8400-e29b-41d4-a716-446655440000"})
        == "collection-uuid:550e8400-e29b-41d4-a716-446655440000"
    )
    with pytest.raises(ValueError, match="namespaced"):
        resolve_collection_identity({"identity": "invalid"})


def test_independent_collection_locks(tmp_path):
    state = CollectionState(tmp_path)
    with state.collection_lock("youtube-playlist:A"), state.collection_lock("youtube-playlist:B"):
        state.record("youtube-playlist:A", "first")
    assert state.completed("youtube-playlist:A") == {"first"}
