"""Ensure the source-derived semantic surface audit remains reproducible."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_semantic_surface_audit_matches_source() -> None:
    script = ROOT / "yt-sql/build_semantic_surface_audit.py"
    spec = importlib.util.spec_from_file_location("portable_semantic_surface_audit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/SEMANTIC-SURFACE-AUDIT.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert "MISMATCH" in actual["lexer_token_alternatives"]
    assert any(item["module"] == "query_resolver.py" for item in actual["rejection_and_exception_sites"])
