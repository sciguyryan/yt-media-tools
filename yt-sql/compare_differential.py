"""Check both evaluator optimisation paths against approved portable expectations.

This is an additional execution check, never an expectation generator.
A mismatch between paths is not sufficient evidence of which path is correct:
both must independently satisfy the normative expected outcome.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare_outcomes import outcomes_match
from run_python_candidate import observe
from validate_corpus import ROOT, _load, validate_corpus


def compare_case(case: Path, *, root: Path = ROOT) -> dict[str, object]:
    """Return three independent comparison verdicts for an approved case."""
    manifest = _load(case / "test.json")
    expected = _load(case / "expected.json")
    configurations = manifest.get("execution", {}).get("configurations", [{"id": "default"}])
    if len(configurations) != 1:
        raise ValueError(f"{manifest['id']}: differential runner requires one declared configuration")
    configuration = configurations[0]["id"]
    enabled = observe(case, root=root, configuration=configuration, optimisation_override="enabled")
    disabled = observe(case, root=root, configuration=configuration, optimisation_override="disabled")
    options = {"order": manifest["order"], "group_sizes": manifest.get("group_sizes")}
    return {
        "id": manifest["id"],
        "enabled_matches_expected": outcomes_match(expected, enabled, **options),
        "disabled_matches_expected": outcomes_match(expected, disabled, **options),
        "paths_agree": outcomes_match(enabled, disabled, **options),
    }


def run(*, root: Path = ROOT) -> list[dict[str, object]]:
    """Run every approved case; fail closed on adapter or comparison errors."""
    validate_corpus(root)
    return [compare_case(path.parent, root=root) for path in sorted((root / "cases").rglob("test.json"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = run(root=args.root)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            if not all(value for key, value in item.items() if key != "id"):
                print(f"FAIL {item['id']}: {item}")
        print(
            f"Differential cases: {len(results)}; fully equivalent: {sum(all(v for k, v in item.items() if k != 'id') for item in results)}"
        )
    return int(any(not all(v for k, v in item.items() if k != "id") for item in results))


if __name__ == "__main__":
    raise SystemExit(main())
