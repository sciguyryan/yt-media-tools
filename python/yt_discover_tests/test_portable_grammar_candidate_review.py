"""Guard the curated classification of discovered grammar candidates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_grammar_candidate_review_matches_source() -> None:
    script = ROOT / "yt-sql/build_grammar_candidate_review.py"
    spec = importlib.util.spec_from_file_location("portable_grammar_candidate_review", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = json.loads((ROOT / "yt-sql/GRAMMAR-CANDIDATE-REVIEW.json").read_text(encoding="utf-8"))
    assert actual == module.generate()
    assert all(not entry["approved_case_ids"] for entry in actual["keyword_candidates"])
