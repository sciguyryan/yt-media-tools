"""Check the reproducible Phase 1 coverage assessment."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase1_coverage_assessment_matches_sources():
    script = ROOT / "yt-sql/build_phase1_coverage_assessment.py"
    spec = importlib.util.spec_from_file_location("phase1_coverage_assessment", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/PHASE1-COVERAGE-ASSESSMENT.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert actual["summary"]["approved_cases"] == 0
    assert actual["review_queues"]["recognised_unsupported_forms_needing_negative_cases"]
