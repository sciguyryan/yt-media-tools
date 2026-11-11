"""Check semantics-preserving query transport changes against normative outcomes.

These transformations deliberately avoid rewriting SQL tokens: quoted strings,
comments and identifiers must retain their original meaning. This is a narrow
metamorphic check, not a claim of comprehensive query rewrite equivalence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from compare_outcomes import outcomes_match
from run_python_candidate import observe
from validate_corpus import ROOT, _load, validate_corpus


def variants(query: str) -> dict[str, str]:
    """Return distinct, semantics-preserving surrounding-whitespace variants."""
    return {
        "surrounding-whitespace": "\n\t" + query + "\n\t",
        "crlf-transport": "\r\n" + query.replace("\r\n", "\n").replace("\n", "\r\n") + "\r\n",
    }


def compare_case(case: Path, *, root: Path = ROOT) -> dict[str, object]:
    manifest = _load(case / "test.json")
    expected = _load(case / "expected.json")
    configurations = manifest.get("execution", {}).get("configurations", [{"id": "default"}])
    if len(configurations) != 1:
        raise ValueError(f"{manifest['id']}: metamorphic runner requires one declared configuration")
    configuration = configurations[0]["id"]
    options = {"order": manifest["order"], "group_sizes": manifest.get("group_sizes")}
    baseline = observe(case, root=root, configuration=configuration)
    results: dict[str, object] = {
        "id": manifest["id"],
        "baseline_matches_expected": outcomes_match(expected, baseline, **options),
    }
    query = (case / "query.ysql").read_text(encoding="utf-8")
    # A temporary case contains only the original contract and a transformed
    # query. Dataset references continue to resolve against the original root.
    with TemporaryDirectory(prefix="yt-sql-metamorphic-") as directory:
        temporary = Path(directory)
        for filename in ("test.json", "expected.json"):
            (temporary / filename).write_bytes((case / filename).read_bytes())
        for name, transformed in variants(query).items():
            (temporary / "query.ysql").write_bytes(transformed.encode("utf-8"))
            observed = observe(temporary, root=root, configuration=configuration)
            results[f"{name}_matches_expected"] = outcomes_match(expected, observed, **options)
            results[f"{name}_matches_baseline"] = outcomes_match(baseline, observed, **options)
    return results


def run(*, root: Path = ROOT) -> list[dict[str, object]]:
    validate_corpus(root)
    return [compare_case(path.parent, root=root) for path in sorted((root / "cases").rglob("test.json"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = run(root=args.root)
    failures = [item for item in results if not all(value for key, value in item.items() if key != "id")]
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in failures:
            print(f"FAIL {item['id']}: {item}")
        print(f"Metamorphic cases: {len(results)}; fully equivalent: {len(results) - len(failures)}")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
