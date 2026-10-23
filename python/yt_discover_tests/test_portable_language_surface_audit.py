"""Static contract checks for the portable language-surface audit."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_language_surface_audit_matches_source() -> None:
    import importlib.util

    script = ROOT / "yt-sql/build_language_surface_audit.py"
    spec = importlib.util.spec_from_file_location("portable_language_surface_audit", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/LANGUAGE-SURFACE-AUDIT.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert actual["status"] == "static_discovery_not_grammar_or_semantic_certification"
    assert actual["parser_methods"]
    assert actual["diagnostic_raise_sites"]
