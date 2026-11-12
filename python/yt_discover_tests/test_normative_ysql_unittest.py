"""Expose each approved portable YT-SQL case as a selectable unittest method.

The normative query and expectation remain in yt-sql/cases, not in this adapter.
Shards are selected by sorted ordinal so parallel workers have disjoint work.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "yt-sql"))

from compare_outcomes import outcomes_match  # noqa: E402
from run_python_candidate import observe  # noqa: E402
from validate_corpus import _load, validate_corpus  # noqa: E402

CORPUS = PROJECT / "yt-sql"


def selected_cases(*, shard_index: int = 0, shard_count: int = 1) -> list[tuple[str, Path]]:
    """Validate once and return disjoint, deterministically ordered cases."""
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("shard index must be between zero and shard count minus one")
    validate_corpus(CORPUS)
    entries = sorted((_load(path)["id"], path.parent) for path in (CORPUS / "cases").rglob("test.json"))
    selected_id = os.environ.get("YTSQL_CASE_ID")
    if selected_id and selected_id not in {case_id for case_id, _ in entries}:
        raise ValueError(f"unknown normative case ID: {selected_id}")
    return [
        entry
        for index, entry in enumerate(entries)
        if index % shard_count == shard_index and (selected_id is None or entry[0] == selected_id)
    ]


def _case_test(case_id: str, directory: Path):
    def test(self: unittest.TestCase) -> None:
        manifest = _load(directory / "test.json")
        expected = _load(directory / "expected.json")
        actual = observe(directory, root=CORPUS)
        match = outcomes_match(expected, actual, order=manifest["order"], group_sizes=manifest.get("group_sizes"))
        self.assertTrue(
            match,
            f"{case_id}\nQuery: {directory / 'query.ysql'}\nExpected: {expected!r}\nObserved: {actual!r}",
        )

    return test


def build_case_class(*, shard_index: int = 0, shard_count: int = 1) -> type[unittest.TestCase]:
    """Create stable test method names suitable for unittest -k selection."""
    methods = {}
    for case_id, directory in selected_cases(shard_index=shard_index, shard_count=shard_count):
        name = "test_" + "".join(char if char.isalnum() and char.isascii() else "_" for char in case_id)
        if name in methods:
            raise ValueError(f"portable case method collision: {name}")
        methods[name] = _case_test(case_id, directory)
    return type("NormativeYTSQLCases", (unittest.TestCase,), methods)


# unittest discovery imports this module once; do not invoke the whole corpus
# from each test method or revalidate it for every query.
NormativeYTSQLCases = build_case_class(
    shard_index=int(os.environ.get("YTSQL_SHARD_INDEX", "0")),
    shard_count=int(os.environ.get("YTSQL_SHARD_COUNT", "1")),
)
