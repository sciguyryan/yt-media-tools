"""Keep the lexical operator spelling audit reproducible."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_operator_spelling_audit_matches_source() -> None:
    script = ROOT / "yt-sql/build_operator_spelling_audit.py"
    spec = importlib.util.spec_from_file_location("portable_operator_spelling_audit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected = json.loads((ROOT / "yt-sql/OPERATOR-SPELLING-AUDIT.json").read_text(encoding="utf-8"))
    assert expected == module.generate()
