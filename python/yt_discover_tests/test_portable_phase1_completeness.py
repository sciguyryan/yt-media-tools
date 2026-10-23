"""Check the consolidated Phase 1 obligations against current source inventories."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_phase1_completeness_matches_source() -> None:
    script = ROOT / "yt-sql/build_phase1_completeness.py"
    spec = importlib.util.spec_from_file_location("phase1_completeness", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/PHASE1-COMPLETENESS.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert actual["registry"]["approved_element_count"] == 0
    assert actual["function_review"]["total"] == 19
