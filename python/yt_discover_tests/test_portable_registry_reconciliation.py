"""Ensure reviewed source classifications remain consistent with the registry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_language_registry_reconciliation_matches_source() -> None:
    script = ROOT / "yt-sql/reconcile_language_elements.py"
    spec = importlib.util.spec_from_file_location("portable_registry_reconciliation", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stored = json.loads((ROOT / "yt-sql/LANGUAGE-REGISTRY-RECONCILIATION.json").read_text(encoding="utf-8"))
    assert stored == module.expected()
    registry = json.loads((ROOT / "yt-sql/LANGUAGE-ELEMENTS.json").read_text(encoding="utf-8"))
    for entry in registry["elements"]:
        if entry["id"] in {"keyword:" + x for x in module.KEYWORDS} | {"operator:" + x for x in module.OPERATORS}:
            assert entry["review_status"] == "pending"
            assert entry["approved_case_ids"] == []
    assert not ({"keyword:" + x for x in module.REJECTED} & {e["id"] for e in registry["elements"]})
