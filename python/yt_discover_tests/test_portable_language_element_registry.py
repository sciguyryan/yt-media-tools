"""Static consistency checks for the curated YT-SQL language-element registry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_language_element_audit_matches_registry() -> None:
    script = ROOT / "yt-sql/build_language_element_registry.py"
    spec = importlib.util.spec_from_file_location("portable_language_element_registry", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/LANGUAGE-ELEMENT-AUDIT.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert not actual["source_discovery_unregistered"]
