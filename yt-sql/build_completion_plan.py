"""Generate the reviewed Phase 7 work allocation without claiming conformance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "PHASE7-COMPLETION-PLAN.json"
DIMENSIONS = (
    "valid_syntax",
    "invalid_syntax",
    "semantics",
    "types_and_null",
    "boundaries",
    "interactions",
    "adversarial",
)


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def allocation(element: dict) -> list[int]:
    name = element["name"].lower()
    if element["category"] == "function" or any(
        part in name for part in ("unicode", "text", "string", "date", "time", "duration", "collection", "random")
    ):
        primary = 3
    else:
        primary = 2
    return [primary, 4, 5, 6]


def generate() -> dict:
    registry = load("LANGUAGE-ELEMENTS.json")
    completeness = load("PHASE1-COMPLETENESS.json")
    gap = load("COVERAGE-GAP-MATRIX.json")
    if tuple(gap["dimensions"]) != DIMENSIONS:
        raise ValueError("Coverage dimensions changed; review allocation and policy")
    elements = registry["elements"]
    ids = [element["id"] for element in elements]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate language element IDs")
    if len(elements) != completeness["registry"]["total"]:
        raise ValueError("Phase 1 registry count has drifted")
    return {
        "version": 1,
        "status": "planned_not_certified",
        "source_files": ["LANGUAGE-ELEMENTS.json", "PHASE1-COMPLETENESS.json", "COVERAGE-GAP-MATRIX.json"],
        "coverage_dimensions": list(DIMENSIONS),
        "phases": {
            "1": "Reconcile source inventory, obligations and unsupported syntax; no semantic certification",
            "2": "Core expressions, ordering, pagination, relational and set semantics",
            "3": "Functions, collections, Unicode, temporal and type semantics",
            "4": "Negative, boundary, adversarial and interaction tests",
            "5": "Python/Rust, optimiser and platform differential verification",
            "6": "Evidence reconciliation and final certification gate",
        },
        "elements": [
            {
                "id": element["id"],
                "category": element["category"],
                "primary_phase": allocation(element)[0],
                "required_phases": allocation(element),
                "required_dimensions": list(DIMENSIONS),
                "coverage_status": "unverified",
                "approved_case_ids": element.get("approved_case_ids", []),
            }
            for element in sorted(elements, key=lambda entry: entry["id"])
        ],
        "unsupported_syntax_negative_case_queue": completeness["grammar_review"]["recognised_unsupported_forms"],
        "certification_rule": "Every applicable dimension requires independently reviewed case evidence or an explicit reviewed not-applicable reason; tagged legacy tests and generated outputs are not proof.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            print(f"{OUTPUT.name} is stale")
            return 1
        print(f"{OUTPUT.name} is current")
        return 0
    OUTPUT.write_text(content, encoding="utf-8")
    print(f"Wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
