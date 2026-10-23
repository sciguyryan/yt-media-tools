"""Classify discovered grammar candidates without claiming normative test coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECONCILIATION = ROOT / "yt-sql/GRAMMAR-RECONCILIATION.json"
OUTPUT = ROOT / "yt-sql/GRAMMAR-CANDIDATE-REVIEW.json"

# Deliberately curated from the hand-written parser. Unsupported forms are
# recognised for diagnostics, not registered as supported syntax.
REJECTION_ONLY = {"RECURSIVE", "RIGHT", "FULL", "CROSS", "NATURAL"}
SUPPORTED = {
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
}
TOKEN_ROLES = {
    "LPAREN": "opening parenthesis",
    "RPAREN": "closing parenthesis",
    "RBRACKET": "closing bracket",
}


def generate() -> dict[str, object]:
    data = json.loads(RECONCILIATION.read_text(encoding="utf-8"))
    candidates = {entry["word"] for entry in data["literal_keyword_calls"]} & (REJECTION_ONLY | SUPPORTED)
    classified = REJECTION_ONLY | SUPPORTED
    if candidates != classified:
        raise ValueError(
            f"Keyword candidate drift: missing classifications {sorted(candidates - classified)}; obsolete classifications {sorted(classified - candidates)}"
        )
    tokens = set(data["unmatched_token_candidates"])
    if tokens != set(TOKEN_ROLES):
        raise ValueError(f"Token candidate drift: {sorted(tokens ^ set(TOKEN_ROLES))}")
    sites = {entry["word"]: entry["methods"] for entry in data["literal_keyword_calls"]}
    token_sites = {entry["token"]: entry["methods"] for entry in data["literal_token_calls"]}
    return {
        "version": 1,
        "status": "source_review_provisional_not_normative_coverage",
        "keyword_candidates": [
            {
                "word": word,
                "classification": "recognised_unsupported_form"
                if word in REJECTION_ONLY
                else "supported_syntax_candidate",
                "parser_methods": sites[word],
                "approved_case_ids": [],
                "semantic_review": "pending",
            }
            for word in sorted(candidates)
        ],
        "token_candidates": [
            {
                "token": token,
                "role": TOKEN_ROLES[token],
                "parser_methods": token_sites[token],
                "classification": "structural_token_not_language_keyword",
                "approved_case_ids": [],
            }
            for token in sorted(tokens)
        ],
        "next_actions": [
            "Verify supported candidates against complete parser and evaluator semantics before adding curated registry entries.",
            "Keep unsupported forms as explicit negative-test requirements rather than supported-feature registrations.",
            "Review aliases and operator spellings from the lexer independently of keyword-call discovery.",
            "Do not credit source classifications or existing Python cases as approved portable conformance tests.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("GRAMMAR-CANDIDATE-REVIEW.json is stale; regenerate it")
        print("GRAMMAR-CANDIDATE-REVIEW.json is current")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print("Updated GRAMMAR-CANDIDATE-REVIEW.json")


if __name__ == "__main__":
    main()
