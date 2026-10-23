"""Exercise the versioned tied-order outcome comparison contract."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
SPEC = importlib.util.spec_from_file_location("portable_tied_outcomes", ROOT / "yt-sql/compare_outcomes.py")
assert SPEC and SPEC.loader
outcomes = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(outcomes)


def _rows(rows: list[list[object]]) -> dict[str, object]:
    return {"version": 1, "outcome": "rows", "columns": ["value"], "rows": rows}


def test_tied_outcome_accepts_permutations_but_not_cross_group_changes() -> None:
    expected = _rows([["a"], ["a"], ["b"], ["c"]])
    assert outcomes.outcomes_match(expected, _rows([["a"], ["a"], ["c"], ["b"]]), order="tied", group_sizes=[2, 2])
    assert not outcomes.outcomes_match(expected, _rows([["b"], ["a"], ["a"], ["c"]]), order="tied", group_sizes=[2, 2])
    assert not outcomes.outcomes_match(expected, _rows([["a"], ["b"], ["b"], ["c"]]), order="tied", group_sizes=[2, 2])


def test_tied_outcome_rejects_invalid_contract() -> None:
    expected = _rows([["a"], ["b"]])
    with pytest.raises(outcomes.OutcomeError, match="requires group_sizes"):
        outcomes.outcomes_match(expected, expected, order="tied")
    with pytest.raises(outcomes.OutcomeError, match="forbid"):
        outcomes.outcomes_match(expected, expected, order="ordered", group_sizes=[2])
    with pytest.raises(outcomes.OutcomeError, match="partition"):
        outcomes.outcomes_match(expected, expected, order="tied", group_sizes=[1])
