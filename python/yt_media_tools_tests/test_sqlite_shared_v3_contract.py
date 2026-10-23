"""Check that historical v3 validation uses the canonical SQLite statements."""

from pathlib import Path
import sqlite3

from yt_media_tools.sqlite import load_statement


_STATEMENTS = (
    "v3_metadata_records",
    "v3_observation_timestamps",
    "v3_entry_timestamps",
    "v3_coverage_timestamps",
    "v3_frontier_timestamps",
    "v3_entry_sources",
    "v3_entry_indexes",
    "v3_frontiers",
    "v3_ordered_entry_ids",
)


def test_v3_contract_statements_have_canonical_resources():
    root = Path(__file__).resolve().parents[2] / "common" / "sqlite" / "statements" / "cache_v3"
    # Other tests may have loaded a statement before a local SQLFluff rewrite.
    # Clear the loader cache so this checks the current canonical file contents.
    load_statement.cache_clear()
    for name in _STATEMENTS:
        assert load_statement(f"cache_v3/{name}") == (root / f"{name}.sql").read_text(encoding="utf-8").strip()


def test_v3_contract_parameter_counts_are_stable():
    for name in _STATEMENTS:
        expected = 1 if name in {"v3_entry_indexes", "v3_ordered_entry_ids"} else 0
        assert load_statement(f"cache_v3/{name}").count("?") == expected


def test_v3_entry_timestamps_preserves_identity_then_timestamp():
    """The historical validator unpacks the identity before the timestamp."""
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE TABLE source_entries (source_url TEXT, video_id TEXT, observed_at TEXT)")
        db.execute(
            "INSERT INTO source_entries VALUES (?, ?, ?)",
            ("source-a", "video-b", "2020-01-02T03:04:05Z"),
        )
        cursor = db.execute(load_statement("cache_v3/v3_entry_timestamps"))
        assert [column[0] for column in cursor.description] == ["entry_identity", "observed_at"]
        assert cursor.fetchall() == [("source-a/video-b", "2020-01-02T03:04:05Z")]
