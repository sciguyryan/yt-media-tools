"""Seeded lexical stress tests against independently reviewed portable expectations.

This runner does not generate normative expectations. Every successful mutation
must continue to satisfy the original approved expectation. Only lexically safe
transformations are used; strings, quoted identifiers and comments are opaque.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from compare_outcomes import outcomes_match
from run_python_candidate import observe
from validate_corpus import ROOT, _load, validate_corpus

KEYWORDS = frozenset(
    "SELECT FROM WHERE AND OR NOT AS DISTINCT ORDER BY ASC DESC LIMIT OFFSET "
    "GROUP HAVING JOIN INNER LEFT ON UNION ALL WITH CASE WHEN THEN ELSE END "
    "IS NULL TRUE FALSE IN BETWEEN LIKE ESCAPE COUNT SUM AVG MIN MAX "
    "COALESCE NULLIF LOWER UPPER LENGTH CONCAT GREATEST LEAST POSITION "
    "FILTER MAP CARDINALITY CHAR RANDOM".split()
)
TOKEN = re.compile(
    r"(?:'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/|"
    r"@[A-Za-z_][A-Za-z_0-9]*|:[A-Za-z_][A-Za-z_0-9]*|"
    r"[A-Za-z_][A-Za-z_0-9]*|\s+|.)"
)


def lexical_variants(query: str, seed: int, count: int) -> list[str]:
    """Produce deterministic keyword-case and safe layout perturbations.

    Existing whitespace is replaced only where it already separates tokens;
    punctuation and quoted content are never changed. A space is always retained
    so adjacent identifiers cannot merge, and line comments retain their newline.
    """
    if count < 1:
        raise ValueError("count must be positive")
    tokens = TOKEN.findall(query)
    result: list[str] = []
    for iteration in range(count):
        rng = random.Random(f"{seed}:{iteration}")
        output: list[str] = []
        previous = ""
        for token in tokens:
            if token.isspace():
                if previous.startswith("--"):
                    output.append(token)
                elif "\n" in token:
                    output.append(rng.choice(["\n", "\n  ", "\n\t", " \n "]))
                else:
                    output.append(rng.choice([" ", "  ", "\t", " \t "]))
            elif token.upper() in KEYWORDS and token.isascii() and token.isalpha():
                output.append(rng.choice([token.upper(), token.lower(), token]))
            else:
                output.append(token)
            if not token.isspace():
                previous = token
        result.append("".join(output))
    return result


def check_case(case: Path, *, root: Path, seed: int, variants: int) -> dict[str, object]:
    manifest = _load(case / "test.json")
    expected = _load(case / "expected.json")
    configurations = manifest.get("execution", {}).get("configurations", [{"id": "default"}])
    if len(configurations) != 1:
        return {"id": manifest["id"], "status": "skipped", "reason": "multiple configurations"}
    configuration = configurations[0]["id"]
    options = {"order": manifest["order"], "group_sizes": manifest.get("group_sizes")}
    query = (case / "query.ysql").read_text(encoding="utf-8")
    case_seed = int.from_bytes(hashlib.sha256(manifest["id"].encode()).digest()[:8], "big") ^ seed
    baseline = observe(case, root=root, configuration=configuration)
    if not outcomes_match(expected, baseline, **options):
        return {"id": manifest["id"], "status": "failed", "reason": "baseline differs from normative expectation"}
    with TemporaryDirectory(prefix="yt-sql-torture-") as directory:
        temporary = Path(directory)
        for filename in ("test.json", "expected.json"):
            (temporary / filename).write_bytes((case / filename).read_bytes())
        for index, variant in enumerate(lexical_variants(query, case_seed, variants)):
            (temporary / "query.ysql").write_text(variant, encoding="utf-8")
            try:
                observed = observe(temporary, root=root, configuration=configuration)
            except Exception as exc:
                return {
                    "id": manifest["id"],
                    "status": "failed",
                    "variant": index,
                    "reason": f"{type(exc).__name__}: {exc}",
                    "query": variant,
                }
            if not outcomes_match(expected, observed, **options):
                return {
                    "id": manifest["id"],
                    "status": "failed",
                    "variant": index,
                    "reason": "mutated result differs from normative expectation",
                    "query": variant,
                }
    return {"id": manifest["id"], "status": "passed", "variants": variants}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--seed", type=int, default=6404)
    parser.add_argument("--variants", type=int, default=4)
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.variants < 1 or args.variants > 1000:
        parser.error("--variants must be between 1 and 1000")
    validate_corpus(args.root)
    cases = sorted((args.root / "cases").rglob("test.json"))
    if args.case:
        cases = [case for case in cases if _load(case)["id"] in set(args.case)]
        if len(cases) != len(set(args.case)):
            parser.error("unknown or duplicated case ID")
    results = [check_case(case.parent, root=args.root, seed=args.seed, variants=args.variants) for case in cases]
    failures = [entry for entry in results if entry["status"] == "failed"]
    if args.json:
        print(json.dumps({"seed": args.seed, "variants": args.variants, "results": results}, indent=2))
    else:
        for failure in failures:
            print(f"FAIL {failure['id']}: {failure['reason']}")
        print(f"Seed {args.seed}: {len(results)} cases, {len(failures)} failures")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
