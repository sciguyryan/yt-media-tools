"""Inventory legacy assertions and normative evidence without assuming equivalence.

This is a migration planning aid, not a semantic certification mechanism. A
matching feature tag or test name cannot establish replacement coverage.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = ROOT / "python/yt_discover_tests"
SQL_ROOT = ROOT / "yt-sql"
OUTPUT = SQL_ROOT / "SEMANTIC-RETIREMENT-AUDIT.json"
DIMENSIONS = (
    "valid_syntax",
    "invalid_syntax",
    "semantics",
    "types_and_null",
    "boundaries",
    "interactions",
    "adversarial",
)


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def assertion_sites(tree: ast.AST) -> list[dict[str, object]]:
    """Inventory assertion kinds without coupling the report to formatting line numbers."""
    sites = []
    for node in ast.walk(tree):
        kind = None
        if isinstance(node, ast.Assert):
            kind = "assert"
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if name.startswith("assert") or name in {"raises", "warns", "fail"}:
                kind = name
        if kind:
            sites.append({"kind": kind})
    return sorted(sites, key=lambda site: site["kind"])


def build() -> dict[str, object]:
    registry = read_json(SQL_ROOT / "LANGUAGE-ELEMENTS.json")
    plan = read_json(SQL_ROOT / "PHASE7-COMPLETION-PLAN.json")
    inventory = read_json(SQL_ROOT / "EXISTING-TEST-INVENTORY.json")
    gap = read_json(SQL_ROOT / "COVERAGE-GAP-MATRIX.json")
    elements = registry["elements"]
    planned = {entry["id"]: entry for entry in plan["elements"]}
    if len({entry["id"] for entry in elements}) != len(elements):
        raise ValueError("Duplicate language element identifiers")
    if set(planned) != {entry["id"] for entry in elements}:
        raise ValueError("Completion plan and language registry differ")
    if tuple(plan["coverage_dimensions"]) != DIMENSIONS or tuple(gap["dimensions"]) != DIMENSIONS:
        raise ValueError("Coverage dimensions changed; review the audit generator")

    manifests = {}
    for path in sorted((SQL_ROOT / "cases").rglob("test.json")):
        case = read_json(path)
        identifier = case["id"]
        if identifier in manifests:
            raise ValueError(f"Duplicate normative case: {identifier}")
        manifests[identifier] = str(path.relative_to(ROOT))

    files = []
    for path in sorted(TEST_ROOT.rglob("test_*.py")):
        relative = str(path.relative_to(ROOT))
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        tests = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                sites = assertion_sites(node)
                tests.append(
                    {
                        "name": node.name,
                        "assertion_sites": sites,
                        "replacement_case_ids": [],
                        "replacement_review": "not_reviewed",
                    }
                )
        files.append(
            {
                "path": relative,
                "previous_classification": inventory["python_test_files"].get(relative),
                "tests": sorted(tests, key=lambda test: test["name"]),
                "retirement_decision": "retain_pending_assertion_level_review",
            }
        )
    if set(inventory["python_test_files"]) != {entry["path"] for entry in files}:
        raise ValueError("Existing-test inventory differs; rebuild it before this audit")

    retirement_path = SQL_ROOT / "REVIEWED-RETIREMENTS.json"
    retirements = read_json(retirement_path) if retirement_path.exists() else {"version": 1, "retirements": []}
    if retirements["version"] != 1:
        raise ValueError("Unsupported retirement evidence version")
    for retirement in retirements["retirements"]:
        source = ROOT / retirement["source"]
        if not source.is_file() or not retirement["case_ids"] or retirement["assertions"] < 1:
            raise ValueError(f"Incomplete retirement evidence: {retirement}")
        names = {
            node.name
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if retirement["test"] in names:
            raise ValueError(f"Retired test is still present: {retirement['test']}")
        missing = sorted(set(retirement["case_ids"]) - set(manifests))
        if missing:
            raise ValueError(f"Missing replacement cases for {retirement['test']}: {missing}")

    mapped = []
    for element in elements:
        entry = planned[element["id"]]
        reviewed = entry.get("approved_case_ids", [])
        unknown = sorted(set(reviewed) - set(manifests))
        if unknown:
            raise ValueError(f"Unknown normative cases for {element['id']}: {unknown}")
        mapped.append(
            {
                "id": element["id"],
                "category": element["category"],
                "primary_phase": entry["primary_phase"],
                "required_dimensions": entry["required_dimensions"],
                "reviewed_case_ids": reviewed,
                "dimension_evidence": {
                    dimension: {"status": "pending_review", "case_ids": [], "not_applicable_reason": None}
                    for dimension in entry["required_dimensions"]
                },
                "migration_status": "not_certified",
            }
        )
    counts = Counter()
    for item in files:
        counts["test_functions"] += len(item["tests"])
        counts["assertion_sites"] += sum(len(test["assertion_sites"]) for test in item["tests"])
    return {
        "version": 1,
        "status": "discovery_only_no_semantic_replacements_certified",
        "sources": [
            "yt-sql/LANGUAGE-ELEMENTS.json",
            "yt-sql/PHASE7-COMPLETION-PLAN.json",
            "yt-sql/COVERAGE-GAP-MATRIX.json",
            "yt-sql/EXISTING-TEST-INVENTORY.json",
            "yt-sql/REVIEWED-RETIREMENTS.json",
        ],
        "counts": {
            "language_elements": len(elements),
            "normative_manifests": len(manifests),
            "legacy_test_files": len(files),
            **dict(counts),
        },
        "normative_cases": [{"id": key, "manifest": value} for key, value in sorted(manifests.items())],
        "language_obligations": mapped,
        "legacy_tests": files,
        "reviewed_retirements": retirements["retirements"],
        "retirement_policy": (
            "Every legacy semantic assertion needs an independently reviewed normative replacement "
            "before retirement. Retain implementation-specific assertions and infrastructure tests. "
            "No equivalence or coverage is inferred from names, tags or successful execution alone."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the committed audit is current")
    args = parser.parse_args()
    result = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != result:
            raise SystemExit("Semantic retirement audit differs: rebuild it")
        print("Semantic retirement audit is current")
    else:
        OUTPUT.write_text(result, encoding="utf-8")
        print(f"Updated {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
