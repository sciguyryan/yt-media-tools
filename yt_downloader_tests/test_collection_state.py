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


def test_ordered_fingerprint_is_stable_and_sensitive_to_order_and_duplicates():
    from yt_media_tools.collection_state import fingerprint_collection_sequence

    original = fingerprint_collection_sequence(["A", "B", "A"])
    assert original == fingerprint_collection_sequence(["A", "B", "A"])
    assert original != fingerprint_collection_sequence(["A", "A", "B"])
    assert original != fingerprint_collection_sequence(["A", "B"])
    assert original != fingerprint_collection_sequence(["A", "B", "A", "C"])
    assert fingerprint_collection_sequence(["a\nb", "c"]) != fingerprint_collection_sequence(["a", "b\nc"])
    assert fingerprint_collection_sequence(["e\u0301"]) != fingerprint_collection_sequence(["\u00e9"])
    with pytest.raises(ValueError, match="non-empty"):
        fingerprint_collection_sequence([""])


def test_observation_survives_completion_cleanup(tmp_path):
    from yt_media_tools.collection_state import SEQUENCE_FINGERPRINT_VERSION, fingerprint_collection_sequence

    state = CollectionState(tmp_path)
    identity = "youtube-playlist:A"
    state.record(identity, "A")
    state.record_observation(identity, ["A", "B", "A"])
    assert state.observation(identity) == (
        SEQUENCE_FINGERPRINT_VERSION,
        fingerprint_collection_sequence(["A", "B", "A"]),
        3,
    )
    state.clear(identity)
    assert state.completed(identity) == set()
    assert CollectionState(tmp_path).observation(identity) is not None
    state.record_observation(identity, ["B", "A"])
    assert state.observation(identity)[2] == 2
    assert state.observation("youtube-playlist:other") is None


def test_v1_migration_preserves_completion_and_is_idempotent(tmp_path):
    from yt_media_tools.collection_state import SCHEMA_VERSION

    state = CollectionState(tmp_path)
    with sqlite3.connect(state.path) as connection:
        connection.execute(
            "CREATE TABLE completed_targets (collection_id TEXT NOT NULL, target_id TEXT NOT NULL, completed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')), PRIMARY KEY (collection_id, target_id))"
        )
        connection.execute(
            "INSERT INTO completed_targets (collection_id, target_id) VALUES (?, ?)", ("youtube-playlist:A", "A")
        )
        connection.execute("PRAGMA user_version = 1")
    assert state.completed("youtube-playlist:A") == {"A"}
    assert state.observation("youtube-playlist:A") is None
    with sqlite3.connect(state.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert CollectionState(tmp_path).completed("youtube-playlist:A") == {"A"}


def test_invalid_v1_layout_not_migrated(tmp_path):
    state = CollectionState(tmp_path)
    with sqlite3.connect(state.path) as connection:
        connection.execute("CREATE TABLE unexpected (value TEXT)")
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(CollectionStateError, match="unsupported"):
        state.completed("youtube-playlist:A")
    with sqlite3.connect(state.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute("SELECT name FROM sqlite_master WHERE name='unexpected'").fetchone()
