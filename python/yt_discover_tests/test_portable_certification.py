"""Phase 6.6 certification gate for the portable YT-SQL corpus.

The committed CERTIFICATION.json records the certified subset: every coverage
cell is reviewed or explicitly deferred, the Python candidate reproduces every
approved expectation, and the gap matrix is current. Cross-implementation
adapters target this certified subset.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
import build_certification  # noqa: E402

ARTEFACT = ROOT / "yt-sql/CERTIFICATION.json"


def test_certification_gate_holds() -> None:
    actual = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    generated = build_certification.generate()
    assert actual == generated
    assert generated["status"] == "certified"
    for condition in generated["gate"]:
        assert condition["satisfied"], condition["condition"]
    # A certified artefact never hides a silent gap: every deferred cell must
    # be attributed to a named feature with recorded justifications.
    counts = generated["conformance"]["counts"]
    assert counts["fail"] == counts["error"] == counts["xpass"] == 0
    function_cells = generated["coverage"]["function_cells"]
    assert function_cells["reviewed"] == function_cells["total"]
    deferred = generated["coverage"]["deferred_features"]
    assert len(deferred) > 0
    assert generated["coverage"]["deferred_cells"] == sum(len(entry["deferred_dimensions"]) for entry in deferred)
