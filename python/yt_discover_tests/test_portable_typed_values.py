"""Portable typed result contract and comparison regressions."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_typed_values", ROOT / "yt-sql/typed_values.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_order_and_duplicate_multiplicity() -> None:
    first = [["a"], ["b"], ["a"]]
    second = [["a"], ["a"], ["b"]]
    assert module.compare_rows(first, second, ordered=False)
    assert not module.compare_rows(first, second, ordered=True)
    assert not module.compare_rows(first, [["a"], ["b"]], ordered=False)


def test_null_boolean_and_text_are_distinct() -> None:
    assert not module.compare_rows([[None]], [["null"]], ordered=False)
    assert not module.compare_rows([[True]], [["true"]], ordered=False)
    assert not module.compare_rows([["é"]], [["e\u0301"]], ordered=False)


def test_exact_numeric_and_timestamp_semantics() -> None:
    integer = {"type": "integer", "value": "9007199254740993"}
    assert module.compare_rows([[integer]], [[integer]], ordered=True)
    assert not module.compare_rows([[integer]], [[{"type": "decimal", "value": "9007199254740993"}]], ordered=True)
    assert module.compare_rows(
        [[{"type": "decimal", "value": "1.00"}]], [[{"type": "decimal", "value": "1.0"}]], ordered=True
    )
    assert module.compare_rows(
        [[{"type": "timestamp", "value": "2026-01-01T00:00:00Z"}]],
        [[{"type": "timestamp", "value": "2025-12-31T19:00:00-05:00"}]],
        ordered=True,
    )


@pytest.mark.parametrize(
    "value",
    [
        1,
        1.0,
        {"type": "integer", "value": "01"},
        {"type": "decimal", "value": "NaN"},
        {"type": "timestamp", "value": "2026-01-01"},
        {"type": "timestamp", "value": "2026-02-30T00:00:00Z"},
        {"type": "text", "value": "x"},
        "\ud800",
    ],
)
def test_reject_ambiguous_values(value: object) -> None:
    with pytest.raises(module.TypedValueError):
        module.validate_values([[value]], 1)


def test_row_width_validation() -> None:
    with pytest.raises(module.TypedValueError):
        module.validate_values([["a", "b"]], 1)
