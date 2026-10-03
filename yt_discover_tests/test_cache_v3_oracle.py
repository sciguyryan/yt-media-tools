"""Semantic oracle checks for the canonical historical cache-v3 fixture."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cache_v3"
FIXTURE = FIXTURE_DIR / "canonical-valid-v3.sqlite3"
ORACLE = FIXTURE_DIR / "canonical-valid-v3.oracle.json"


def _oracle() -> dict[str, object]:
    return json.loads(ORACLE.read_text(encoding="utf-8"))


def _rows(query: str) -> list[tuple[object, ...]]:
    db = sqlite3.connect(f"file:{FIXTURE}?mode=ro", uri=True)
    try:
        return db.execute(query).fetchall()
    finally:
        db.close()


def test_v3_oracle_is_versioned_and_does_not_describe_a_v4_schema() -> None:
    oracle = _oracle()
    assert oracle["oracle_version"] == 1
    assert oracle["source_cache_schema_version"] == 3
    assert "v4 physical schema" in str(oracle["purpose"])
    encoded = json.dumps(oracle, ensure_ascii=False).lower()
    for forbidden in ("v4_table", "v4_column", "provider_id", "entity_id"):
        assert forbidden not in encoded


def test_v3_oracle_metadata_facts_match_the_sqlite_fixture() -> None:
    expected = []
    for source_url, video_id, fetched_at, raw_json in _rows(
        "SELECT source_url, video_id, fetched_at, raw_json FROM metadata_records ORDER BY source_url, video_id"
    ):
        expected.append(
            {
                "source_url": source_url,
                "video_id": video_id,
                "fetched_at": fetched_at,
                "record": json.loads(str(raw_json)),
            }
        )
    assert _oracle()["facts"]["metadata_records"] == expected


def test_v3_oracle_source_state_matches_the_sqlite_fixture() -> None:
    oracle = _oracle()["facts"]
    specifications = {
        "source_observations": (
            "SELECT source_url, source_kind, last_observed_at, observed_entries FROM source_observations ORDER BY source_url",
            ("source_url", "source_kind", "last_observed_at", "observed_entries"),
        ),
        "source_entries": (
            "SELECT source_url, video_id, source_index, observed_at FROM source_entries ORDER BY source_url, source_index",
            ("source_url", "video_id", "source_index", "observed_at"),
        ),
        "source_coverage": (
            "SELECT source_url, source_kind, observed_at, observed_entries, cached_entries, complete, reason FROM source_coverage ORDER BY source_url",
            ("source_url", "source_kind", "observed_at", "observed_entries", "cached_entries", "complete", "reason"),
        ),
        "source_frontiers": (
            "SELECT source_url, source_kind, verified_at, known_entries, head_video_id, overlap_confirmations FROM source_frontiers ORDER BY source_url",
            ("source_url", "source_kind", "verified_at", "known_entries", "head_video_id", "overlap_confirmations"),
        ),
    }
    for name, (query, fields) in specifications.items():
        expected = [dict(zip(fields, row, strict=True)) for row in _rows(query)]
        if name == "source_coverage":
            for row in expected:
                row["complete"] = bool(row["complete"])
        assert oracle[name] == expected


def test_v3_oracle_preserves_source_scoped_duplicate_media_and_snapshot_meaning() -> None:
    facts = _oracle()["facts"]
    shared = [row for row in facts["metadata_records"] if row["video_id"] == "shared-video"]
    assert len(shared) == 2
    assert {row["source_url"] for row in shared} == {
        "https://www.youtube.com/@fixture/videos",
        "https://www.youtube.com/@fixture/shorts",
    }
    partial = next(row for row in facts["source_coverage"] if row["source_url"] == "https://example.invalid/partial")
    detailed_partial = [
        row for row in facts["metadata_records"] if row["source_url"] == "https://example.invalid/partial"
    ]
    assert partial["cached_entries"] == 1
    assert len(detailed_partial) == 2


def test_v3_oracle_records_the_resolved_historical_raw_json_boundary() -> None:
    classification = _oracle()["semantic_classification"]
    historical = " ".join(classification["historical_raw_json_boundary"])
    assert "former raw.* namespace" in historical
    assert "registered scalars and collection families" in historical
    assert "discards arbitrary unregistered remainder" in historical
    absent = " ".join(classification["not_recoverable_from_v3"])
    assert "YouTube.js" in absent
    assert "ytmusicapi" in absent
