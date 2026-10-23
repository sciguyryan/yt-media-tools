"""Check that the textual predicate audit remains reproducible."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_textual_predicate_audit_matches_source() -> None:
    script = ROOT / "yt-sql/build_textual_predicate_audit.py"
    spec = importlib.util.spec_from_file_location("portable_textual_predicate_audit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = json.loads((ROOT / "yt-sql/TEXTUAL-PREDICATE-AUDIT.json").read_text(encoding="utf-8"))
    assert expected == module.generate()


def test_textual_predicate_audit_rejects_missing_parser_evidence() -> None:
    script = ROOT / "yt-sql/build_textual_predicate_audit.py"
    spec = importlib.util.spec_from_file_location("portable_textual_predicate_audit_negative", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = module.FAMILIES
    try:
        module.FAMILIES = {"deliberate_drift": ("NOT_A_YTSQL_KEYWORD",)}
        try:
            module.generate()
        except ValueError as exc:
            assert "no longer have parser call evidence" in str(exc)
        else:
            raise AssertionError("Missing grammar evidence must fail")
    finally:
        module.FAMILIES = original
