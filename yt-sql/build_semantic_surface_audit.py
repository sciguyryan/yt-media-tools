"""Discover lexical alternatives and semantic rejection sites without certifying coverage."""

from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "python/yt_media_tools"
OUTPUT = ROOT / "yt-sql/SEMANTIC-SURFACE-AUDIT.json"
MODULES = ("query_parser.py", "query_resolver.py", "query_evaluator.py")


def _scope(tree: ast.AST, node: ast.AST) -> str:
    """Return the nearest enclosing named function, not a physical line number."""
    scopes: dict[ast.AST, str] = {}

    def visit(current: ast.AST, path: tuple[str, ...]) -> None:
        next_path = path
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            next_path = (*path, current.name)
        scopes[current] = ".".join(next_path) if next_path else "<module>"
        for child in ast.iter_child_nodes(current):
            visit(child, next_path)

    visit(tree, ())
    return scopes[node]


def _lexical_groups(tree: ast.AST) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_TOKEN_RE" for target in node.targets
        ):
            if isinstance(node.value, ast.Call) and node.value.args:
                try:
                    pattern = ast.literal_eval(node.value.args[0])
                except (ValueError, TypeError):
                    return []
                return re.findall(r"\(\?P<([A-Za-z_][A-Za-z_0-9]*)>", pattern)
    return []


def generate() -> dict[str, object]:
    diagnostics: list[dict[str, object]] = []
    conditional_branches: list[dict[str, object]] = []
    parser_groups: list[str] = []
    for filename in MODULES:
        tree = ast.parse((PACKAGE / filename).read_text(encoding="utf-8"), filename=filename)
        if filename == "query_parser.py":
            parser_groups = _lexical_groups(tree)
        diagnostic_counts: Counter[tuple[str, str]] = Counter()
        branch_counts: Counter[tuple[str, str]] = Counter()
        for node in ast.walk(tree):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                call = node.exc.func
                exception = (
                    call.id if isinstance(call, ast.Name) else call.attr if isinstance(call, ast.Attribute) else None
                )
                if exception is not None:
                    diagnostic_counts[(_scope(tree, node), exception)] += 1
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                branch_counts[(_scope(tree, node), type(node).__name__)] += 1
        diagnostics.extend(
            {"module": filename, "scope": scope, "exception": exception, "sites": count}
            for (scope, exception), count in sorted(diagnostic_counts.items())
        )
        conditional_branches.extend(
            {"module": filename, "scope": scope, "kind": kind, "sites": count}
            for (scope, kind), count in sorted(branch_counts.items())
        )
    return {
        "version": 1,
        "status": "structural_discovery_only_not_semantic_certification",
        "sources": [f"python/yt_media_tools/{name}" for name in MODULES],
        "lexer_token_alternatives": parser_groups,
        "rejection_and_exception_sites": diagnostics,
        "conditional_branch_sites": conditional_branches,
        "limitations": [
            "Lexer alternatives are extracted from the recursive-descent lexer, not an exhaustive grammar specification.",
            "Raised exception names include implementation failures as well as language diagnostics; classification requires review.",
            "Conditional branch counts indicate investigation targets, not independent grammar alternatives or test coverage.",
            "The hand-written parser grammar and semantic acceptance/rejection paths require manual examination.",
            "No discovered item counts as an approved conformance test.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the committed audit without rewriting it")
    args = parser.parse_args()
    generated = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            raise SystemExit("SEMANTIC-SURFACE-AUDIT.json is stale; regenerate it")
        print("SEMANTIC-SURFACE-AUDIT.json is current")
    else:
        OUTPUT.write_text(generated, encoding="utf-8")
        print("Updated SEMANTIC-SURFACE-AUDIT.json")


if __name__ == "__main__":
    main()
