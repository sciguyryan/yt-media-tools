"""Ordering-key tie groups preserve group sequence, not within-group encounter order."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_tied_values", ROOT / "yt-sql/typed_values.py")
assert SPEC and SPEC.loader
values = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(values)


def test_permutations_within_ties_are_valid() -> None:
    expected = [["a"], ["a"], ["b"], ["c"], ["d"]]
    observed = [["a"], ["a"], ["c"], ["b"], ["d"]]
    assert values.compare_tied_groups(expected, observed, group_sizes=[2, 2, 1])
    assert not values.compare_rows(expected, observed, ordered=True)


def test_group_crossing_and_duplicate_loss_are_rejected() -> None:
    expected = [["a"], ["a"], ["b"], ["c"]]
    assert not values.compare_tied_groups(expected, [["b"], ["a"], ["a"], ["c"]], group_sizes=[2, 2])
    assert not values.compare_tied_groups(expected, [["a"], ["b"], ["b"], ["c"]], group_sizes=[2, 2])


def test_typed_values_remain_distinct_within_groups() -> None:
    expected = [[None], ["null"], [{"type": "integer", "value": "2"}]]
    assert values.compare_tied_groups(expected, [expected[1], expected[0], expected[2]], group_sizes=[2, 1])
    assert not values.compare_tied_groups(expected, [["null"], ["null"], expected[2]], group_sizes=[2, 1])


@pytest.mark.parametrize("sizes", [[3], [0, 2], [True, 1], [-1, 3], [], [1.0, 1]])
def test_invalid_group_partitions_are_rejected(sizes: list[int]) -> None:
    with pytest.raises(values.TypedValueError, match="invalid tied-group partition"):
        values.compare_tied_groups([["a"], ["b"]], [["a"], ["b"]], group_sizes=sizes)
