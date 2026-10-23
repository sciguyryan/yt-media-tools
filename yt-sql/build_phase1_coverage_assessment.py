"""Consolidate Phase 1 language-surface findings without certifying coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def generate() -> dict:
    registry = load("LANGUAGE-ELEMENTS.json")
    grammar = load("GRAMMAR-CANDIDATE-REVIEW.json")
    symbolic = load("OPERATOR-SPELLING-AUDIT.json")
    textual = load("TEXTUAL-PREDICATE-AUDIT.json")
    elements = registry["elements"]
    registered = {(e["category"], e["name"]) for e in elements}
    supported = sorted(
        {c["word"] for c in grammar["keyword_candidates"] if c["classification"] == "supported_syntax_candidate"}
    )
    rejected = sorted(
        {c["word"] for c in grammar["keyword_candidates"] if c["classification"] == "recognised_unsupported_form"}
    )
    missing_keywords = [w for w in supported if ("keyword", w) not in registered]
    missing_symbols = sorted(
        {e["spelling"] for e in symbolic["symbolic_lexer_spellings"] if ("operator", e["spelling"]) not in registered}
    )
    textual_missing = sorted(
        {w["spelling"] for f in textual["families"] for w in f["words"] if not w["keyword_registry_entry"]}
    )
    return {
        "version": 1,
        "status": "provisional_actionable_review_not_certified_coverage",
        "summary": {
            "registered_elements": len(elements),
            "reviewed_elements": sum(e["review_status"] == "reviewed" for e in elements),
            "approved_cases": len(registry["approved_cases"]),
        },
        "review_queues": {
            "supported_keyword_candidates_missing_registry": missing_keywords,
            "symbolic_lexer_tokens_missing_operator_registry": missing_symbols,
            "textual_predicate_spellings_missing_keyword_registry": textual_missing,
            "recognised_unsupported_forms_needing_negative_cases": rejected,
        },
        "priority_actions": [
            "Confirm candidate spellings against actual lexer, parser and evaluator semantics before curating registry entries.",
            "Separate arithmetic operators, wildcard tokens and punctuation from predicate operators where appropriate.",
            "Record explicit negative cases for deliberately unsupported grammar forms without registering them as supported syntax.",
            "Review each function signature and every semantic rejection category, including type, arity and nullability behaviour.",
            "Produce approved portable cases before claiming minimum CI coverage; candidate results cannot satisfy the gate.",
            "Keep the curated registry under review because static source discovery cannot prove completeness.",
        ],
        "coverage_policy": "No candidate expectation is authoritative until reviewed and approved; the review mechanism and reviewer are not prescribed.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    path = HERE / "PHASE1-COVERAGE-ASSESSMENT.json"
    expected = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not path.exists() or path.read_text(encoding="utf-8") != expected:
            print(f"{path.name} is out of date")
            return 1
        print(f"{path.name} is current")
    else:
        path.write_text(expected, encoding="utf-8")
        print(f"Generated {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
