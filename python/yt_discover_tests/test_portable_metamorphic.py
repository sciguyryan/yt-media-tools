"""Portable metamorphic checks retain independently authored expectations."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2] / "yt-sql"
sys.path.insert(0, str(ROOT))
from compare_metamorphic import compare_case, variants  # noqa: E402
from validate_corpus import _load  # noqa: E402

CASES = sorted((ROOT / "cases").rglob("test.json"))


@pytest.mark.parametrize("manifest_path", CASES, ids=lambda path: _load(path)["id"])
def test_transport_variants_match_normative_expectations(manifest_path: Path) -> None:
    result = compare_case(manifest_path.parent)
    assert all(value for key, value in result.items() if key != "id"), result


def test_variants_preserve_quoted_content_and_are_distinct() -> None:
    query = "SELECT 'a  b', 'x\\ny' FROM @yt_sql_fixture\n"
    transformed = variants(query)
    assert len(set(transformed.values())) == 2
    assert all("'a  b'" in value and "'x\\ny'" in value for value in transformed.values())
