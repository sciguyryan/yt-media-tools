"""Behavioural differential checks against independently authored expectations."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2] / "yt-sql"
sys.path.insert(0, str(ROOT))
from compare_differential import compare_case  # noqa: E402
from validate_corpus import _load  # noqa: E402

CASES = sorted((ROOT / "cases").rglob("test.json"))


@pytest.mark.parametrize("manifest_path", CASES, ids=lambda path: _load(path)["id"])
def test_optimisation_paths_match_normative_expectations(manifest_path: Path) -> None:
    result = compare_case(manifest_path.parent)
    assert result["enabled_matches_expected"], result
    assert result["disabled_matches_expected"], result
    assert result["paths_agree"], result


def test_invalid_optimisation_override_is_rejected() -> None:
    from run_python_candidate import AdapterError, observe

    with pytest.raises(AdapterError, match="optimisation override"):
        observe(CASES[0].parent, optimisation_override="unknown")
