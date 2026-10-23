"""Engine-neutral comparison of observable YT-SQL results and diagnostics."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
SPEC = importlib.util.spec_from_file_location("portable_outcome_comparison", ROOT / "yt-sql/compare_outcomes.py")
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def rows(columns: list[str], values: list[list[object]]) -> dict[str, object]:
    return {"version": 1, "outcome": "rows", "columns": columns, "rows": values}


def error(category: str, code: str | None = None) -> dict[str, object]:
    diagnostic = {"category": category}
    if code is not None:
        diagnostic["code"] = code
    return {"version": 1, "outcome": "error", "error": diagnostic}


def test_order_and_duplicate_multiplicity() -> None:
    expected = rows(["value"], [["a"], ["b"], ["a"]])
    reversed_rows = rows(["value"], [["a"], ["a"], ["b"]])
    assert module.outcomes_match(expected, reversed_rows, order="unordered")
    assert not module.outcomes_match(expected, reversed_rows, order="ordered")
    assert not module.outcomes_match(expected, rows(["value"], [["a"], ["b"]]), order="unordered")


def test_columns_are_normative_even_for_empty_results() -> None:
    assert not module.outcomes_match(rows(["a"], []), rows(["b"], []), order="unordered")
    assert not module.outcomes_match(rows(["a", "b"], []), rows(["b", "a"], []), order="ordered")


def test_diagnostic_category_and_optional_code() -> None:
    assert module.outcomes_match(error("resolution"), error("resolution", "resolution.unknown_column"), order="ordered")
    assert module.outcomes_match(
        error("resolution", "resolution.unknown_column"),
        error("resolution", "resolution.unknown_column"),
        order="unordered",
    )
    assert not module.outcomes_match(error("resolution"), error("syntax"), order="ordered")
    assert not module.outcomes_match(
        error("resolution", "resolution.unknown_column"), error("resolution", "resolution.other"), order="ordered"
    )
    assert not module.outcomes_match(error("resolution"), rows([], []), order="ordered")


@pytest.mark.parametrize(
    "observed",
    [
        None,
        {},
        {"version": 1, "outcome": "error", "error": {"category": "crash"}},
        {"version": 1, "outcome": "error", "error": {"category": "syntax", "message": "translated"}},
        {"version": 1, "outcome": "rows", "columns": [], "rows": [[1]]},
    ],
)
def test_unclassified_or_malformed_observations_fail(observed: object) -> None:
    with pytest.raises(module.OutcomeError):
        module.outcomes_match(error("syntax"), observed, order="ordered")


def test_invalid_order_fails() -> None:
    with pytest.raises(module.OutcomeError):
        module.outcomes_match(rows([], []), rows([], []), order="any")


def test_exact_types_and_timestamp_instants() -> None:
    integer = {"type": "integer", "value": "1"}
    decimal = {"type": "decimal", "value": "1"}
    assert not module.outcomes_match(rows(["x"], [[integer]]), rows(["x"], [[decimal]]), order="ordered")
    first = {"type": "timestamp", "value": "2026-01-01T00:00:00Z"}
    second = {"type": "timestamp", "value": "2025-12-31T19:00:00-05:00"}
    assert module.outcomes_match(rows(["x"], [[first]]), rows(["x"], [[second]]), order="ordered")
