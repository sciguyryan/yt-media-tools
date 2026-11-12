"""Keep the conservative cross-module text and POSITION migration worklist current."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-sql" / "audit_text_position_remaining.py"


def _module():
    spec = importlib.util.spec_from_file_location("text_position_remaining_audit", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_text_position_remaining_index_is_current() -> None:
    module = _module()
    actual = json.loads(module.OUTPUT.read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert actual["status"] == "investigation_only_not_retirement_authority"
    assert all(entry["disposition"] == "retain_pending_assertion_level_review" for entry in actual["functions"])


def test_text_position_inventory_detects_known_legacy_surfaces() -> None:
    entries = {(item["source"], item["test"]) for item in _module().generate()["functions"]}
    assert ("python/yt_discover_tests/test_like_predicates.py", "test_like_semantics") in entries
    assert (
        "python/yt_discover_tests/test_final_position_language.py",
        "test_position_projection_parses_and_canonicalises",
    ) in entries
