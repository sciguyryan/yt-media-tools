"""Generate a conservative, source-derived YT-SQL parser surface audit."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "python/yt_media_tools/query_parser.py"
COVERAGE = ROOT / "yt-sql/COVERAGE-INVENTORY.json"
OUTPUT = ROOT / "yt-sql/LANGUAGE-SURFACE-AUDIT.json"


def _constant_string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def generate() -> dict[str, object]:
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    baseline = json.loads(COVERAGE.read_text(encoding="utf-8"))
    parser_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Parser")
    methods = []
    keywords: dict[str, set[str]] = {}
    diagnostics = []
    for method in parser_class.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if method.name.startswith("parse_"):
            methods.append({"name": method.name})
        for node in ast.walk(method):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"keyword", "consume_keyword", "expect_keyword"}
                and node.args
            ):
                word = _constant_string(node.args[0])
                if word is not None:
                    keywords.setdefault(word, set()).add(method.name)
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                fn = node.exc.func
                error = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if error and ("Error" in error):
                    diagnostics.append({"method": method.name, "exception": error})
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
            "tokenise",
            "_scan_identifier",
            "_parse_number_text",
            "_parse_integer_literal_text",
        }:
            for sub in ast.walk(node):
                if isinstance(sub, ast.Raise) and isinstance(sub.exc, ast.Call):
                    fn = sub.exc.func
                    error = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                    if error and "Error" in error:
                        diagnostics.append({"method": node.name, "exception": error})
    functions = baseline["parser_functions"]
    cases = baseline["feature_to_existing_cases"]
    untagged = sorted(name for name in baseline["registered_features"] if not cases.get(name))
    return {
        "version": 1,
        "status": "static_discovery_not_grammar_or_semantic_certification",
        "sources": {"parser": str(PARSER.relative_to(ROOT)), "coverage": str(COVERAGE.relative_to(ROOT))},
        "parser_methods": sorted(methods, key=lambda item: item["name"]),
        "literal_keyword_calls": {key: sorted(value) for key, value in sorted(keywords.items())},
        "diagnostic_raise_sites": sorted(diagnostics, key=lambda item: (item["method"], item["exception"])),
        "function_names": functions,
        "registered_features_without_tagged_existing_cases": untagged,
        "review_priorities": [
            "Audit grammar alternatives and token definitions not discoverable from literal keyword calls.",
            "Verify function arity, aliases, argument types, NULL behaviour and diagnostic categories against runtime semantics.",
            "Map each supported grammar production, operator and function to positive, negative, boundary and interaction cases.",
            "Treat existing case feature tags as evidence of intent, not verified coverage.",
            "Audit resolver, semantic and evaluator rejection paths separately from parser errors.",
            "Keep candidate expected results provisional until their intended semantics are reviewed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the committed report is current")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("LANGUAGE-SURFACE-AUDIT.json is stale; regenerate the audit")
        print("LANGUAGE-SURFACE-AUDIT.json is current")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print("Updated LANGUAGE-SURFACE-AUDIT.json")


if __name__ == "__main__":
    main()
