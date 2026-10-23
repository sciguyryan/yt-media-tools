"""Audit the curated YT-SQL language-element registry against source inventories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "yt-sql/LANGUAGE-ELEMENTS.json"
COVERAGE = ROOT / "yt-sql/COVERAGE-INVENTORY.json"
MATRIX = ROOT / "yt-sql/COVERAGE-GAP-MATRIX.json"
REPORT = ROOT / "yt-sql/LANGUAGE-ELEMENT-AUDIT.json"


def generate() -> dict[str, object]:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    entries = registry["elements"]
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError("Language element IDs must be unique and sorted")
    valid_categories = {"feature", "keyword", "function", "operator", "syntax", "alias"}
    for item in entries:
        if item["category"] not in valid_categories:
            raise ValueError(f"Invalid category: {item['id']}")
        if item["review_status"] not in {"pending", "reviewed"}:
            raise ValueError(f"Invalid review status: {item['id']}")
        if not isinstance(item["approved_case_ids"], list) or len(item["approved_case_ids"]) != len(
            set(item["approved_case_ids"])
        ):
            raise ValueError(f"Invalid approved case list: {item['id']}")
        if item["review_status"] == "pending" and item["approved_case_ids"]:
            raise ValueError(f"Pending entry claims approved cases: {item['id']}")
    known = {(item["category"], item["name"]) for item in entries}
    discovered = {("feature", name) for name in coverage["registered_features"]} | {
        ("function", item["name"]) for item in matrix["functions"]
    }
    missing = sorted(discovered - known)
    approved = {case["id"] for case in registry.get("approved_cases", [])}
    unknown_references = sorted({case for item in entries for case in item["approved_case_ids"]} - approved)
    if missing or unknown_references:
        raise ValueError(f"Unregistered source elements: {missing}; unknown approved cases: {unknown_references}")
    return {
        "version": 1,
        "status": "provisional_registry_no_normative_cases_yet",
        "registered_elements": len(entries),
        "reviewed_elements": sum(item["review_status"] == "reviewed" for item in entries),
        "elements_with_approved_cases": sum(bool(item["approved_case_ids"]) for item in entries),
        "source_discovery_unregistered": missing,
        "uncertified_elements": [item["id"] for item in entries if not item["approved_case_ids"]],
        "limitations": [
            "The curated registry is not provably exhaustive; source discovery is only a drift signal.",
            "Approved cases must be reviewed against YT-SQL semantics before being registered.",
            "A case association does not establish comprehensive semantic coverage.",
            "The minimum approved-case CI gate remains deferred until normative cases exist.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not REPORT.exists() or REPORT.read_text(encoding="utf-8") != output:
            raise SystemExit("LANGUAGE-ELEMENT-AUDIT.json is stale; regenerate it")
        print("LANGUAGE-ELEMENT-AUDIT.json is current")
    else:
        REPORT.write_text(output, encoding="utf-8")
        print("Updated LANGUAGE-ELEMENT-AUDIT.json")


if __name__ == "__main__":
    main()
