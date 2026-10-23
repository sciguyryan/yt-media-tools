"""Audit lexical operator spellings against the curated YT-SQL registry."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "python/yt_media_tools/query_parser.py"
REGISTRY = ROOT / "yt-sql/LANGUAGE-ELEMENTS.json"
OUTPUT = ROOT / "yt-sql/OPERATOR-SPELLING-AUDIT.json"

# These lexer token classes contain standalone symbolic spellings. The lexer
# recognises these characters, but grammatical meaning must still be reviewed.
SYMBOL_CLASSES = ("OP", "STAR", "PLUS", "MINUS", "SLASH", "PERCENT")
# Potential aliases are probes, not a declaration that they are supported.
ALIAS_PROBES = ("&&", "||", "!", "==", "!=", "<>")


def generate() -> dict[str, object]:
    source = PARSER.read_text(encoding="utf-8")
    tree = ast.parse(source)
    regex_text = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "_TOKEN_RE" for target in node.targets
        ):
            if isinstance(node.value, ast.Call) and node.value.args and isinstance(node.value.args[0], ast.Constant):
                regex_text = node.value.args[0].value
    if not isinstance(regex_text, str):
        raise ValueError("Cannot statically resolve _TOKEN_RE")
    lexer = re.compile(regex_text, re.VERBOSE)
    spellings = ("<=", ">=", "!=", "<>", "=", "<", ">", "*", "+", "-", "/", "%")
    recognised = []
    for spelling in spellings:
        match = lexer.fullmatch(spelling)
        if match is None or match.lastgroup not in SYMBOL_CLASSES:
            raise ValueError(f"Expected symbolic lexer spelling changed: {spelling}")
        recognised.append({"spelling": spelling, "token_kind": match.lastgroup})
    probes = []
    for spelling in ALIAS_PROBES:
        match = lexer.fullmatch(spelling)
        probes.append(
            {
                "spelling": spelling,
                "lexed_as_single_token": bool(match and match.lastgroup != "MISMATCH"),
                "token_kind": match.lastgroup if match and match.lastgroup != "MISMATCH" else None,
            }
        )
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    registered = {item["name"] for item in registry["elements"] if item["category"] in {"operator", "alias"}}
    return {
        "version": 1,
        "status": "lexical_evidence_only_not_normative_coverage",
        "symbolic_lexer_spellings": recognised,
        "alias_probes": probes,
        "registered_operator_and_alias_spellings": sorted(registered),
        "lexed_symbolic_spellings_without_registry_entry": sorted(set(spellings) - registered),
        "registered_spellings_not_in_symbolic_lexer_inventory": sorted(registered - set(spellings)),
        "review_requirements": [
            "Distinguish arithmetic and comparison operators from punctuation and wildcard usage in parser context.",
            "Audit textual AND, OR, NOT, IS, IN, BETWEEN, LIKE, ILIKE and other predicate forms separately.",
            "A lexical match alone does not prove a valid grammar construct or operator alias.",
            "Do not register && or || as supported aliases without evidence from the actual hand-written parser.",
            "Add reviewed positive, negative, boundary and interaction tests before granting conformance credit.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            raise SystemExit("OPERATOR-SPELLING-AUDIT.json is stale; regenerate it")
        print("OPERATOR-SPELLING-AUDIT.json is current")
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print("Updated OPERATOR-SPELLING-AUDIT.json")


if __name__ == "__main__":
    main()
