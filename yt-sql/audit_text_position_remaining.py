"""Inventory remaining legacy text and POSITION test functions without authorising retirement.

The index is deliberately conservative: names and string literals are search evidence,
not a claim that an assertion is portable or has been replaced.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "python" / "yt_discover_tests"
OUTPUT = ROOT / "yt-sql" / "TEXT-POSITION-REMAINING.json"
TERMS = ("POSITION", "CHAR", "CONCAT", "LENGTH", "LOWER", "UPPER", "LIKE", "ILIKE", "CONTAINS", "MATCHES", "UNICODE")
PATTERN = re.compile(r"(?<![A-Za-z_])(?:" + "|".join(TERMS) + r")(?![A-Za-z_])", re.IGNORECASE)


def generate() -> dict[str, object]:
    entries = []
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            # AST-scoped evidence avoids matching comments and unrelated neighbouring tests.
            evidence = [node.name]
            evidence.extend(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))
            terms = sorted({match.group().upper() for value in evidence for match in PATTERN.finditer(value)})
            if not terms:
                continue
            decorators = [ast.unparse(d) for d in node.decorator_list]
            entries.append(
                {
                    "source": path.relative_to(ROOT).as_posix(),
                    "test": node.name,
                    "terms": terms,
                    "assert_sites": sum(isinstance(n, (ast.Assert, ast.Raise)) for n in ast.walk(node)),
                    "parametrised": any("parametrize" in d for d in decorators),
                    "disposition": "retain_pending_assertion_level_review",
                }
            )
    return {
        "version": 1,
        "status": "investigation_only_not_retirement_authority",
        "method": "AST function names and string literals; no automatic portability classification",
        "functions": entries,
        "limitations": [
            "Dynamic query construction and helper calls can hide additional relevant assertions.",
            "A matching name or literal is not evidence of normative equivalence.",
            "Parameterised tests may represent more than one assertion or semantic obligation.",
            "Nonmatching tests are not certified as unrelated; cross-module manual review remains necessary.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            parser.error("Text/POSITION remaining-assertion index is stale; regenerate it")
    else:
        OUTPUT.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
