"""Generate a stable investigation index for registered function semantics and rejection sites."""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "python/yt_media_tools"
COVERAGE = ROOT / "yt-sql/COVERAGE-INVENTORY.json"
GAPS = ROOT / "yt-sql/COVERAGE-GAP-MATRIX.json"
OUTPUT = ROOT / "yt-sql/FUNCTION-SEMANTIC-AUDIT.json"
MODULES = ("query_parser.py", "query_resolver.py", "query_evaluator.py")


def _scope_map(tree: ast.AST) -> dict[ast.AST, str]:
    scopes: dict[ast.AST, str] = {}

    def visit(node: ast.AST, parents: tuple[str, ...]) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parents = (*parents, node.name)
        scopes[node] = ".".join(parents) or "<module>"
        for child in ast.iter_child_nodes(node):
            visit(child, parents)

    visit(tree, ())
    return scopes


def _exception(node: ast.Raise) -> str | None:
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    return None


def generate() -> dict[str, object]:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    gaps = json.loads(GAPS.read_text(encoding="utf-8"))
    functions = {entry["name"]: entry for entry in gaps["functions"]}
    registered = set(coverage["parser_functions"]["scalar"]) | set(coverage["parser_functions"]["aggregate"])
    if set(functions) != registered:
        raise ValueError("Function inventory drift: review function registrations")
    sites: list[dict[str, object]] = []
    for filename in MODULES:
        tree = ast.parse((SOURCE / filename).read_text(encoding="utf-8"))
        scopes = _scope_map(tree)
        counts: Counter[tuple[str, str]] = Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise):
                exception = _exception(node)
                if exception:
                    counts[(scopes[node], exception)] += 1
        sites.extend(
            {
                "module": filename,
                "scope": scope,
                "exception": exception,
                "count": count,
                "classification": "requires_review",
            }
            for (scope, exception), count in sorted(counts.items())
        )
    return {
        "version": 1,
        "status": "investigation_only_no_expectations_approved",
        "sources": [f"python/yt_media_tools/{name}" for name in MODULES],
        "functions": [
            {
                "name": name,
                "kind": functions[name]["kind"],
                "parser_argument_shape": functions[name]["parser_argument_shape"],
                "review_requirements": [
                    "arity",
                    "accepted_argument_types",
                    "coercion",
                    "return_type",
                    "null_semantics",
                    "invalid_arguments",
                    "boundary_values",
                    "nested_and_relational_interactions",
                ],
                "review_status": "pending",
            }
            for name in sorted(registered)
        ],
        "exception_sites": sites,
        "limitations": [
            "Function names and parser argument shapes are source-derived; semantic contracts require review.",
            "Exception sites are investigation targets, not necessarily user-facing language errors.",
            "Source locations are represented by structural scopes rather than formatting-sensitive line numbers.",
            "No candidate output or existing feature tag is approved as normative coverage.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("FUNCTION-SEMANTIC-AUDIT.json is stale; regenerate it")
        print("FUNCTION-SEMANTIC-AUDIT.json is current")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print("Updated FUNCTION-SEMANTIC-AUDIT.json")


if __name__ == "__main__":
    main()
