"""Protect the first Phase 7 migration proposal without granting approval."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT / "yt-sql/migration-proposals/offset_limit"


def test_offset_limit_proposal_matches_source_and_independent_fixture_oracle() -> None:
    source = (ROOT / "python/yt_discover_tests/conformance/cases.py").read_text(encoding="utf-8")
    query = (PROPOSAL / "query.sql").read_text(encoding="utf-8").strip()
    assert query in source
    fixture = json.loads((ROOT / "yt-sql/datasets/python-v6-small.json").read_text(encoding="utf-8"))
    eligible = [record for record in fixture["records"] if record["view_count"] is not None]
    eligible.sort(key=lambda record: record["view_count"], reverse=True)
    # This fixture has ties across the selected boundary. The proposed
    # ordering is not normative until tie semantics are independently reviewed.
    counts = [record["view_count"] for record in eligible]
    assert any(counts[i] == counts[i + 1] for i in range(2, 8))
    expected = json.loads((PROPOSAL / "proposed-expected.json").read_text(encoding="utf-8"))
    assert expected == {
        "version": 1,
        "outcome": "rows",
        "columns": ["id"],
        "rows": [[record["id"]] for record in eligible[3:8]],
    }


def test_migration_proposal_is_not_normative() -> None:
    manifest = json.loads((PROPOSAL / "test.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "ordering.offset_limit"
    assert not (ROOT / "yt-sql/cases/ordering/offset_limit").exists()
    assert not (PROPOSAL / "expected.json").exists()
