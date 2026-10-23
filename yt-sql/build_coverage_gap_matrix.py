"""Build a conservative YT-SQL coverage-gap matrix from audited source inventories."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "yt-sql/COVERAGE-INVENTORY.json"
SURFACE = ROOT / "yt-sql/LANGUAGE-SURFACE-AUDIT.json"
PARSER = ROOT / "python/yt_media_tools/query_parser.py"
OUTPUT = ROOT / "yt-sql/COVERAGE-GAP-MATRIX.json"
DIMENSIONS = (
    "valid_syntax",
    "invalid_syntax",
    "semantics",
    "types_and_null",
    "boundaries",
    "interactions",
    "adversarial",
)

# These signatures describe explicit parse_scalar_function checks, not complete
# resolver/evaluator typing contracts. Changes require source review.
SIGNATURES = {
    "LOWER": "exactly_one",
    "UPPER": "exactly_one",
    "LENGTH": "exactly_one",
    "CARDINALITY": "exactly_one",
    "COALESCE": "at_least_two",
    "CONCAT": "at_least_two",
    "CHAR": "at_least_one",
    "NULLIF": "exactly_two",
    "GREATEST": "at_least_two",
    "LEAST": "at_least_two",
    "POSITION": "zero",
    "RANDOM": "zero_or_one",
    "FILTER": "collection_binding_where",
    "MAP": "collection_binding_select",
    "COUNT": "star_or_one_or_collection_binding",
    "SUM": "exactly_one",
    "MIN": "exactly_one",
    "MAX": "exactly_one",
    "AVG": "exactly_one",
}


def _calls(method: ast.FunctionDef, attr: str) -> list[str]:
    values = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attr:
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                values.add(node.args[0].value)
    return sorted(values)


def generate() -> dict[str, object]:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    surface = json.loads(SURFACE.read_text(encoding="utf-8"))
    tree = ast.parse(PARSER.read_text(encoding="utf-8"))
    parser = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Parser")
    methods = {n.name: n for n in parser.body if isinstance(n, ast.FunctionDef)}
    registered = sorted(set(coverage["parser_functions"]["scalar"] + coverage["parser_functions"]["aggregate"]))
    if set(registered) != set(SIGNATURES):
        raise ValueError("Function registry and reviewed parser signatures differ; audit the change")
    features = []
    for name in sorted(coverage["registered_features"]):
        features.append(
            {
                "feature": name,
                "tagged_existing_cases": sorted(coverage["feature_to_existing_cases"].get(name, [])),
                "dimensions": {
                    dimension: {"status": "unverified", "reviewed_case_ids": []} for dimension in DIMENSIONS
                },
            }
        )
    functions = [
        {
            "name": name,
            "kind": "aggregate" if name in coverage["parser_functions"]["aggregate"] else "scalar",
            "parser_argument_shape": SIGNATURES[name],
            "signature_status": "source_review_required_for_semantics_and_types",
            "dimensions": {dimension: {"status": "unverified", "reviewed_case_ids": []} for dimension in DIMENSIONS},
        }
        for name in registered
    ]
    grammar = [
        {
            "method": name,
            "literal_expect_tokens": _calls(method, "expect"),
            "literal_expect_keywords": _calls(method, "expect_keyword"),
            "literal_consume_keywords": _calls(method, "consume_keyword"),
            "alternatives_status": "not_yet_exhaustively_reviewed",
        }
        for name, method in sorted(methods.items())
        if name.startswith("parse_")
    ]
    return {
        "version": 1,
        "status": "gap_discovery_only_no_coverage_certified",
        "source_inventories": ["yt-sql/COVERAGE-INVENTORY.json", "yt-sql/LANGUAGE-SURFACE-AUDIT.json"],
        "dimensions": list(DIMENSIONS),
        "registered_features": features,
        "functions": functions,
        "parser_entry_points": grammar,
        "diagnostic_raise_sites": surface["diagnostic_raise_sites"],
        "unresolved_audit_work": [
            "Inspect hand-written parser grammar alternatives beyond literal token and keyword calls.",
            "Review function signatures, type rules, aliases and runtime semantics against resolver and evaluator.",
            "Classify lexer, parser, resolver and evaluator rejection paths with valid and invalid test cases.",
            "Map independently reviewed cases to coverage dimensions; existing feature tags are not proof.",
            "Include interaction and maximal coherent torture tests before claiming completeness.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the committed report without writing")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("COVERAGE-GAP-MATRIX.json is stale; regenerate it")
        print("COVERAGE-GAP-MATRIX.json is current")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print("Updated COVERAGE-GAP-MATRIX.json")


if __name__ == "__main__":
    main()
