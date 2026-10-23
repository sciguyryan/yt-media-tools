"""Guard the source-derived grammar reconciliation against unnoticed drift."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_grammar_reconciliation_matches_source() -> None:
    script = ROOT / "yt-sql/build_grammar_reconciliation.py"
    spec = importlib.util.spec_from_file_location("portable_grammar_reconciliation", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = json.loads((ROOT / "yt-sql/GRAMMAR-RECONCILIATION.json").read_text(encoding="utf-8"))
    assert committed == module.generate()
    assert committed["parser_implementation"] == "hand_written_recursive_descent"
