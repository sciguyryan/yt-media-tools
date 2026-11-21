"""Protect the reviewed function conformance matrix from accidental case loss."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "yt-sql"
FUNCTIONS = (
    "AVG",
    "CARDINALITY",
    "CHAR",
    "COALESCE",
    "CONCAT",
    "COUNT",
    "FILTER",
    "GREATEST",
    "LEAST",
    "LENGTH",
    "LOWER",
    "MAP",
    "MAX",
    "MIN",
    "NULLIF",
    "POSITION",
    "RANDOM",
    "ROW_NUMBER",
    "SUM",
    "UPPER",
)


def test_every_registered_function_has_portable_examples() -> None:
    """Each registered function needs more than a single happy-path query."""
    audit = json.loads((ROOT / "FUNCTION-SEMANTIC-AUDIT.json").read_text(encoding="utf-8"))
    assert {entry["name"] for entry in audit["functions"]} == set(FUNCTIONS)
    cases = sorted((ROOT / "cases").rglob("test.json"))
    for function in FUNCTIONS:
        matching = [
            path
            for path in cases
            if re.search(rf"\b{function}\s*\(", (path.parent / "query.ysql").read_text(encoding="utf-8"), re.I)
        ]
        assert len(matching) >= 3, f"{function} has insufficient portable conformance cases"
        assert any(
            json.loads((path.parent / "expected.json").read_text(encoding="utf-8"))["outcome"] == "rows"
            for path in matching
        ), f"{function} has no positive expectation"
        assert any(
            json.loads((path.parent / "expected.json").read_text(encoding="utf-8"))["outcome"] == "error"
            for path in matching
        ), f"{function} has no negative expectation"
