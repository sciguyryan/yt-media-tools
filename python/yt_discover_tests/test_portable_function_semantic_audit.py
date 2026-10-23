"""Check the portable function and semantic-rejection investigation index."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_function_semantic_audit_matches_source() -> None:
    path = ROOT / "yt-sql/build_function_semantic_audit.py"
    spec = importlib.util.spec_from_file_location("portable_function_semantic_audit", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/FUNCTION-SEMANTIC-AUDIT.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert {item["name"] for item in actual["functions"]} == {
        item["name"]
        for item in json.loads((ROOT / "yt-sql/COVERAGE-GAP-MATRIX.json").read_text(encoding="utf-8"))["functions"]
    }
    assert all(item["review_status"] == "pending" for item in actual["functions"])
    assert any(item["module"] == "query_evaluator.py" for item in actual["exception_sites"])
