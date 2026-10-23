"""Slice boundaries may intersect equal-key ordering groups."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from typed_values import TypedValueError, compare_tied_slice  # noqa: E402


def test_boundary_ties_allow_alternative_rows() -> None:
    full = [["a"], ["b"], ["c"], ["d"], ["e"], ["f"]]
    assert compare_tied_slice(full, [["c"], ["d"], ["e"]], group_sizes=[1, 3, 2], offset=2, limit=3)
    assert compare_tied_slice(full, [["b"], ["d"], ["f"]], group_sizes=[1, 3, 2], offset=2, limit=3)
    assert not compare_tied_slice(full, [["b"], ["e"], ["c"]], group_sizes=[1, 3, 2], offset=2, limit=3)


def test_duplicate_multiplicity_and_empty_slice() -> None:
    full = [["a"], ["a"], ["b"], ["c"]]
    assert compare_tied_slice(full, [["a"], ["b"]], group_sizes=[3, 1], offset=1, limit=2)
    assert not compare_tied_slice(full, [["b"], ["b"]], group_sizes=[3, 1], offset=1, limit=2)
    assert compare_tied_slice(full, [], group_sizes=[3, 1], offset=10, limit=3)
    assert compare_tied_slice([], [], group_sizes=[], offset=0, limit=3)


@pytest.mark.parametrize(
    "sizes,offset,limit", [([2], 0, 1), ([0, 4], 0, 1), ([4], -1, 1), ([4], 0, -1), ([4], True, 1)]
)
def test_invalid_contract(sizes: list[int], offset: int, limit: int) -> None:
    with pytest.raises(TypedValueError):
        compare_tied_slice([["a"], ["b"], ["c"], ["d"]], [], group_sizes=sizes, offset=offset, limit=limit)
