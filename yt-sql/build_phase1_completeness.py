"""Consolidate Phase 1 review obligations without certifying conformance."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "PHASE1-COMPLETENESS.json"


def load(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def generate() -> dict:
    registry = load("LANGUAGE-ELEMENTS.json")
    assessment = load("PHASE1-COVERAGE-ASSESSMENT.json")
    function_audit = load("FUNCTION-SEMANTIC-AUDIT.json")
    reconciliation = load("LANGUAGE-REGISTRY-RECONCILIATION.json")
    elements = registry["elements"]
    ids = [element["id"] for element in elements]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate curated language-element IDs")
    by_category = dict(sorted(Counter(e["category"] for e in elements).items()))
    approved = [e["id"] for e in elements if e.get("approved_case_ids")]
    functions = sorted(f["name"] for f in function_audit["functions"])
    registered_functions = sorted(e["name"] for e in elements if e["category"] == "function")
    if functions != registered_functions:
        raise ValueError("Function audit and curated registry disagree: review function registration")
    queues = assessment["review_queues"]
    return {
        "version": 1,
        "status": "phase1_review_obligations_not_conformance_certification",
        "registry": {
            "total": len(elements),
            "categories": by_category,
            "approved_element_count": len(approved),
            "pending_element_ids": sorted(e["id"] for e in elements if e.get("review_status") != "reviewed"),
        },
        "function_review": {
            "total": len(functions),
            "names": functions,
            "requirements": sorted(set(req for f in function_audit["functions"] for req in f["review_requirements"])),
        },
        "grammar_review": {
            "unresolved_discovery_queues": {key: sorted(value) for key, value in sorted(queues.items())},
            "recognised_unsupported_forms": sorted(reconciliation["recognised_unsupported_forms"]),
        },
        "phase1_exit_requirements": [
            "Review curated registry entries and classification of supported and rejected forms.",
            "Resolve discovery queues or explicitly document deferred semantic checks.",
            "Record function, operator, grammar and diagnostic conformance obligations for later phases.",
            "Keep generated candidate expectations non-normative until reviewed and approved.",
            "Ensure every inventory and audit generator passes its drift check.",
        ],
        "later_phase_obligations": [
            "Implement approved positive, negative, boundary and interaction cases for each language element.",
            "Independently review reference-generated expectations before approval.",
            "Enable minimum registered-element coverage enforcement only after normative cases exist.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != expected:
            print(f"{OUTPUT.name} is stale; regenerate and review")
            return 1
        print(f"{OUTPUT.name} is current")
        return 0
    OUTPUT.write_text(expected, encoding="utf-8")
    print(f"Wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
