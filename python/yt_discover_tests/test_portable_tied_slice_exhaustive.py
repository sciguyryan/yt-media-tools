"""Exhaustively check tied pagination against an independent permutation oracle."""

from __future__ import annotations

import importlib.util
from itertools import permutations, product
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_tied_slice_values", ROOT / "yt-sql/typed_values.py")
assert SPEC and SPEC.loader
values = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(values)


def _permitted_slices(groups: tuple[tuple[str, ...], ...], offset: int, limit: int) -> set[tuple[str, ...]]:
    """Enumerate complete tie-group orderings without using the comparator."""
    group_orders = [set(permutations(group)) for group in groups]
    return {
        tuple(item for ordering in chosen for item in ordering)[offset : offset + limit]
        for chosen in product(*group_orders)
    }


@pytest.mark.parametrize(
    "groups",
    [
        (("a", "b"), ("c", "d"), ("e",)),
        (("a", "a", "b"), ("c", "c")),
        (("a",), ("b", "c", "d")),
        (("a", "b", "c"),),
    ],
)
def test_tied_pagination_matches_independent_exhaustive_oracle(groups: tuple[tuple[str, ...], ...]) -> None:
    full = tuple(item for group in groups for item in group)
    sizes = [len(group) for group in groups]
    universe = sorted(set(full) | {"outside"})
    for offset in range(len(full) + 2):
        for limit in range(len(full) + 2):
            allowed = _permitted_slices(groups, offset, limit)
            length = len(next(iter(allowed)))
            # Check every candidate of the correct length, including missing,
            # duplicated and out-of-group values. Also reject wrong lengths.
            for candidate in product(universe, repeat=length):
                observed = [[value] for value in candidate]
                assert values.compare_tied_slice(
                    [[value] for value in full],
                    observed,
                    group_sizes=sizes,
                    offset=offset,
                    limit=limit,
                ) == (candidate in allowed), (groups, offset, limit, candidate)
            for wrong_length in {max(0, length - 1), length + 1} - {length}:
                assert not values.compare_tied_slice(
                    [[value] for value in full],
                    [["a"]] * wrong_length,
                    group_sizes=sizes,
                    offset=offset,
                    limit=limit,
                )


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, -1), (True, 1), (0, False), (1.0, 1)])
def test_tied_pagination_rejects_invalid_bounds(offset: object, limit: object) -> None:
    with pytest.raises(values.TypedValueError, match="invalid tied-slice contract"):
        values.compare_tied_slice([["a"]], [["a"]], group_sizes=[1], offset=offset, limit=limit)


@pytest.mark.parametrize("sizes", [[], [0, 2], [1, 0], [True, 1], [1.0, 1], [3], [-1, 3]])
def test_tied_pagination_rejects_invalid_partitions(sizes: list[int]) -> None:
    with pytest.raises(values.TypedValueError, match="invalid tied-slice contract"):
        values.compare_tied_slice([["a"], ["b"]], [["a"]], group_sizes=sizes, offset=0, limit=1)
