"""Guard the Phase 7 migration-proposal boundary for the portable corpus.

Proposals live outside cases/ and cannot be executed as approved expectations.
The first proposal (offset_limit) completed its review and was admitted as
ordering.offset_limit with the tied-order contract, so its proposal directory
has been removed and its language semantics are normative.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROPOSALS = ROOT / "yt-sql/migration-proposals"


def test_completed_offset_limit_proposal_is_normative() -> None:
    case = ROOT / "yt-sql/cases/ordering/offset_limit"
    assert (case / "expected.json").is_file()
    manifest = json.loads((case / "test.json").read_text(encoding="utf-8"))
    assert manifest["order"] == "tied"
    assert manifest["group_sizes"] == [2, 1, 1, 1]


def test_no_pending_proposals_remain() -> None:
    if not PROPOSALS.is_dir():
        return
    pending = [entry for entry in PROPOSALS.iterdir() if entry.is_dir()]
    assert pending == [], pending
