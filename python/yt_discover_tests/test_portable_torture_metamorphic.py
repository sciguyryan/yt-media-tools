"""Seeded lexical torture checks retain independently reviewed outcomes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "yt-sql"
sys.path.insert(0, str(ROOT))
from torture_metamorphic import check_case, lexical_variants  # noqa: E402


@pytest.mark.parametrize("seed", [0, 1, 6404, 2**32 - 1])
def test_lexical_transformations_preserve_literals_and_bindings(seed: int) -> None:
    query = "SELECT 'SeLeCt  FROM', \"ORDER\", :limit FROM @yt_sql_fixture WHERE id = 'x''y'"
    for variant in lexical_variants(query, seed, 16):
        assert "'SeLeCt  FROM'" in variant
        assert '"ORDER"' in variant
        assert ":limit" in variant
        assert "@yt_sql_fixture" in variant
        assert "'x''y'" in variant


def test_seeded_variants_are_reproducible_and_vary() -> None:
    query = "SELECT id, source_index FROM @yt_sql_fixture WHERE source_index > 1 ORDER BY id"
    first = lexical_variants(query, 43, 20)
    assert first == lexical_variants(query, 43, 20)
    assert first != lexical_variants(query, 44, 20)
    assert len(set(first)) > 1


@pytest.mark.parametrize(
    "case",
    ["statement.projection_alias", "statement.left_join_no_match", "scalar.coalesce_null_chain"],
)
def test_selected_relational_and_function_cases_against_normative_expectations(case: str) -> None:
    for manifest in (ROOT / "cases").rglob("test.json"):
        import json

        if json.loads(manifest.read_text(encoding="utf-8"))["id"] == case:
            result = check_case(manifest.parent, root=ROOT, seed=6404, variants=8)
            assert result["status"] == "passed", result
            return
    pytest.fail(f"missing normative case: {case}")
