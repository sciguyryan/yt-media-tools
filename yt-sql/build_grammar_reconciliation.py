"""Reconcile discovered hand-written parser surfaces with the curated registry.

This is a discovery report, not a claim of complete grammar or test coverage.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "python/yt_media_tools/query_parser.py"
REGISTRY = ROOT / "yt-sql/LANGUAGE-ELEMENTS.json"
SURFACE = ROOT / "yt-sql/SEMANTIC-SURFACE-AUDIT.json"
OUTPUT = ROOT / "yt-sql/GRAMMAR-RECONCILIATION.json"


def generate() -> dict[str, object]:
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))
    entries = registry["elements"]
    registered = {(item["category"], item["name"].upper()) for item in entries}
    parser_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Parser")
    methods = [
        node for node in parser_class.body if isinstance(node, ast.FunctionDef) and node.name.startswith("parse_")
    ]
    keyword_calls: dict[str, set[str]] = {}
    token_calls: dict[str, set[str]] = {}
    for method in methods:
        for call in ast.walk(method):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if call.func.attr not in {"consume_keyword", "expect_keyword", "consume", "expect"}:
                continue
            if not call.args or not isinstance(call.args[0], ast.Constant) or not isinstance(call.args[0].value, str):
                continue
            value = call.args[0].value.upper()
            destination = keyword_calls if call.func.attr.endswith("keyword") else token_calls
            destination.setdefault(value, set()).add(method.name)
    keyword_missing = sorted(name for name in keyword_calls if ("keyword", name) not in registered)
    token_missing = sorted(
        name for name in token_calls if ("syntax", name) not in registered and ("operator", name) not in registered
    )
    exceptions = Counter((item["module"], item["exception"]) for item in surface["rejection_and_exception_sites"])
    return {
        "version": 1,
        "status": "discovery_candidates_require_manual_review",
        "parser": "python/yt_media_tools/query_parser.py",
        "parser_implementation": "hand_written_recursive_descent",
        "literal_keyword_calls": [
            {"word": word, "methods": sorted(scopes), "registry_keyword_present": ("keyword", word) in registered}
            for word, scopes in sorted(keyword_calls.items())
        ],
        "literal_token_calls": [
            {"token": token, "methods": sorted(scopes)} for token, scopes in sorted(token_calls.items())
        ],
        "unmatched_keyword_candidates": keyword_missing,
        "unmatched_token_candidates": token_missing,
        "diagnostic_exception_classes_by_module": [
            {"module": module, "exception": exception, "scope_groups": count}
            for (module, exception), count in sorted(exceptions.items())
        ],
        "review_requirements": [
            "Confirm keyword candidates are supported grammar forms, not incidental internal strings.",
            "Confirm token candidates against lexer groups, operator spellings and contextual syntax.",
            "Inspect dynamic and indirect parser branches not visible in literal-call discovery.",
            "Classify diagnostic sites by actual user-facing syntax, semantic and runtime behaviour.",
            "Add missing supported elements to the curated registry only after source review.",
            "Do not count existing tags or generated candidate outputs as approved conformance coverage.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("GRAMMAR-RECONCILIATION.json is stale; regenerate it")
        print("GRAMMAR-RECONCILIATION.json is current")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print("Updated GRAMMAR-RECONCILIATION.json")


if __name__ == "__main__":
    main()
