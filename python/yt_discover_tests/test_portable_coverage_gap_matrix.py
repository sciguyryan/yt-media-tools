"""Static contract for the provisional YT-SQL coverage-gap matrix.

The matrix starts as gap discovery (every cell unverified). Phase 6.6 records
reviewed evidence per cell through COVERAGE-EVIDENCE.json, so cells may now
carry either status; the evidence merge itself is validated by the builder.
"""

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
    # Every cell must be either unverified (gap discovery) or reviewed with
    # cited case IDs and a justification from the evidence file.
    for section in ("registered_features", "functions"):
        for entry in actual[section]:
            for review in entry["dimensions"].values():
                assert review["status"] in {"unverified", "reviewed"}
                if review["status"] == "reviewed":
                    assert review["reviewed_case_ids"]
                    assert review.get("justification")
