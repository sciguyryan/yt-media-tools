"""Static contract for the provisional YT-SQL coverage-gap matrix."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_gap_matrix_matches_source() -> None:
    script = ROOT / "yt-sql/build_coverage_gap_matrix.py"
    spec = importlib.util.spec_from_file_location("portable_coverage_gap_matrix", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/COVERAGE-GAP-MATRIX.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert all(
        all(entry["status"] == "unverified" for entry in feature["dimensions"].values())
        for feature in actual["registered_features"]
    )
