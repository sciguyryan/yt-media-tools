"""Audit hand-written parser keyword predicates and their registry evidence."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "python/yt_media_tools/query_parser.py"
REGISTRY = ROOT / "yt-sql/LANGUAGE-ELEMENTS.json"
OUTPUT = ROOT / "yt-sql/TEXTUAL-PREDICATE-AUDIT.json"

# Curated grammar families, not a claim of complete semantic support or coverage.
FAMILIES = {
    "boolean_connectives": ("AND", "OR", "NOT"),
    "null_and_truth_tests": ("IS", "NULL", "TRUE", "FALSE", "UNKNOWN", "DISTINCT"),
    "range_and_membership": ("BETWEEN", "IN"),
    "text_matching": ("LIKE", "ILIKE", "CONTAIN", "CONTAINS", "MATCH", "MATCHES"),
    "negated_text_predicates": ("DOES", "NOT"),
}


def generate() -> dict[str, object]:
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    sites: dict[str, set[str]] = defaultdict(set)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr not in {"keyword", "consume_keyword", "expect_keyword"}:
                continue
            if child.args and isinstance(child.args[0], ast.Constant) and isinstance(child.args[0].value, str):
                sites[child.args[0].value.upper()].add(node.name)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    keywords = {entry["name"].upper() for entry in registry["elements"] if entry["category"] == "keyword"}
    family_words = {word for words in FAMILIES.values() for word in words}
    absent = sorted(family_words - sites.keys())
    if absent:
        raise ValueError(f"Curated predicate keywords no longer have parser call evidence: {absent}")
    return {
        "version": 1,
        "status": "source_evidence_provisional_not_normative_coverage",
        "families": [
            {
                "name": family,
                "words": [
                    {
                        "spelling": word,
                        "parser_methods": sorted(sites[word]),
                        "keyword_registry_entry": word in keywords,
                        "approved_case_ids": [],
                        "semantic_review": "pending",
                    }
                    for word in words
                ],
            }
            for family, words in sorted(FAMILIES.items())
        ],
        "unregistered_predicate_keyword_spellings": sorted(family_words - keywords),
        "review_requirements": [
            "Review each textual spelling and grammatical context before editing the curated language registry.",
            "Distinguish standalone Boolean connectives from AND within BETWEEN and NOT within compound predicates.",
            "Verify alternative text-predicate spellings and their negated forms independently.",
            "Cover IS [NOT] NULL, truth tests, DISTINCT FROM, BETWEEN and IN with positive and negative cases.",
            "Do not credit lexical or parser-call evidence as approved conformance coverage.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("TEXTUAL-PREDICATE-AUDIT.json is stale; regenerate it")
        print("TEXTUAL-PREDICATE-AUDIT.json is current")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print("Updated TEXTUAL-PREDICATE-AUDIT.json")


if __name__ == "__main__":
    main()
