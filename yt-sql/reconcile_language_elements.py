"""Reconcile explicitly classified parser spellings with the curated registry.

This tool never approves conformance expectations or infers support for new tokens.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Deliberate classifications: a newly discovered spelling requires review of this table.
KEYWORDS = (
    "ALL",
    "BETWEEN",
    "CASE",
    "CONTAIN",
    "CONTAINS",
    "DOES",
    "ELSE",
    "END",
    "FALSE",
    "FILTER",
    "ILIKE",
    "MATCH",
    "MATCHES",
    "NULL",
    "OF",
    "OUTER",
    "THEN",
    "TRUE",
    "WHEN",
)
OPERATORS = ("%", "*", "+", "-", "/")
REJECTED = ("CROSS", "FULL", "NATURAL", "RECURSIVE", "RIGHT")


def load(name: str) -> dict:
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def expected() -> dict:
    grammar = load("GRAMMAR-CANDIDATE-REVIEW.json")
    symbolic = load("OPERATOR-SPELLING-AUDIT.json")
    candidates = grammar["keyword_candidates"]
    found_supported = {x["word"] for x in candidates if x["classification"] == "supported_syntax_candidate"}
    found_rejected = {x["word"] for x in candidates if x["classification"] == "recognised_unsupported_form"}
    known_keywords = {x["name"] for x in load("LANGUAGE-ELEMENTS.json")["elements"] if x["category"] == "keyword"}
    missing = found_supported - known_keywords
    symbols = {x["spelling"] for x in symbolic["symbolic_lexer_spellings"]}
    known_operators = {x["name"] for x in load("LANGUAGE-ELEMENTS.json")["elements"] if x["category"] == "operator"}
    missing_symbols = symbols - known_operators
    if (
        not set(KEYWORDS) <= found_supported
        or not set(KEYWORDS) <= known_keywords
        or not set(OPERATORS) <= symbols
        or not set(OPERATORS) <= known_operators
        or missing
        or missing_symbols
        or found_rejected != set(REJECTED)
    ):
        raise ValueError(
            f"Classification drift: keywords={sorted(missing)}, symbols={sorted(missing_symbols)}, rejected={sorted(found_rejected)}"
        )
    return {
        "version": 1,
        "status": "reviewed_source_classification_not_approved_conformance",
        "supported_keyword_entries_to_add": list(KEYWORDS),
        "symbolic_operator_entries_to_add": list(OPERATORS),
        "recognised_unsupported_forms": list(REJECTED),
        "notes": [
            "These entries reflect parser-source classification only; semantic behaviour and test expectations remain unverified.",
            "The asterisk has both multiplication and wildcard uses and requires separate conformance cases.",
            "Unsupported forms require negative cases and must not be registered as supported keywords.",
            "Unrecognised operator aliases such as && and || must not be registered as supported.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    report = HERE / "LANGUAGE-REGISTRY-RECONCILIATION.json"
    output = json.dumps(expected(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not report.exists() or report.read_text(encoding="utf-8") != output:
            raise SystemExit("LANGUAGE-REGISTRY-RECONCILIATION.json is stale")
        print("LANGUAGE-REGISTRY-RECONCILIATION.json is current")
    else:
        report.write_text(output, encoding="utf-8")
        print("Updated LANGUAGE-REGISTRY-RECONCILIATION.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
