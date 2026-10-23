"""Rebuild the Phase 1 baseline inventory from source without importing the engine."""

from __future__ import annotations

import argparse
import ast
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "python/yt_discover_tests/conformance/cases.py"
PARSER_PATH = ROOT / "python/yt_media_tools/query_parser.py"
OUTPUT = ROOT / "yt-sql/COVERAGE-INVENTORY.json"
EXISTING_OUTPUT = ROOT / "yt-sql/EXISTING-TEST-INVENTORY.json"
CONFORMANCE = ROOT / "python/yt_discover_tests/conformance"
TESTS = ROOT / "python/yt_discover_tests"


def assignment(tree: ast.AST, name: str) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    raise ValueError(f"Missing assignment: {name}")


def literal_strings(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.Set, ast.Tuple, ast.List)):
        return sorted(ast.literal_eval(node))
    if isinstance(node, ast.Call) and node.args:
        return literal_strings(node.args[0])
    raise ValueError("Unexpected feature registry expression")


def existing_inventory(features: list[str], cases: list[dict[str, object]]) -> dict[str, object]:
    """Rebuild the legacy migration audit, retaining human classification decisions."""
    previous = json.loads(EXISTING_OUTPUT.read_text(encoding="utf-8")) if EXISTING_OUTPUT.exists() else {}
    classifications = previous.get("python_test_files", {})
    test_files = sorted(str(path.relative_to(ROOT)) for path in TESTS.rglob("test_*.py") if path.is_file())
    specs = sorted(path.name for path in CONFORMANCE.glob("dataset-spec-v*.json"))
    if not specs:
        raise ValueError("No versioned conformance dataset specifications found")
    latest = max(specs, key=lambda name: int(name.removeprefix("dataset-spec-v").removesuffix(".json")))
    spec = json.loads((CONFORMANCE / latest).read_text(encoding="utf-8"))
    return {
        "source_snapshot": previous.get("source_snapshot", "working_tree"),
        "existing_python_cases": len(cases),
        "existing_case_ids": [case["id"] for case in cases],
        "language_feature_count": len(features),
        "language_features": features,
        "generator_versions": specs,
        "generator_profiles": spec["profiles"],
        "generator_seed": spec["default_seed"],
        "python_test_files": {
            name: classifications.get(name, "retain: implementation/integration pending review") for name in test_files
        },
        "migration_policy": previous.get(
            "migration_policy",
            "Do not remove Python tests until equivalent portable cases have passed and remaining implementation-specific assertions are explicitly retained.",
        ),
    }


def write_or_check(path: Path, report: dict[str, object], check: bool) -> None:
    encoded = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != encoded:
            raise SystemExit(f"{path.relative_to(ROOT)} differs: run python yt-sql/build_coverage_inventory.py")
        print(f"{path.relative_to(ROOT)} is current")
    else:
        path.write_text(encoded, encoding="utf-8")
        print(f"Updated {path.relative_to(ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if committed inventory differs")
    args = parser.parse_args()
    tree = ast.parse(CASES_PATH.read_text(encoding="utf-8"))
    parser_tree = ast.parse(PARSER_PATH.read_text(encoding="utf-8"))
    features = literal_strings(assignment(tree, "LANGUAGE_FEATURES"))
    cases_node = assignment(tree, "CASES")
    cases = []
    by_feature: dict[str, list[str]] = defaultdict(list)
    for node in ast.walk(cases_node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "ConformanceCase":
            continue
        case_id = ast.literal_eval(node.args[0])
        tags = []
        for kw in node.keywords:
            if kw.arg == "features":
                tags = list(ast.literal_eval(kw.value))
        cases.append({"id": case_id, "features": sorted(tags)})
        for tag in tags:
            by_feature[tag].append(case_id)
    functions = {}
    for node in ast.walk(parser_tree):
        if isinstance(node, ast.FunctionDef) and node.name == "parse_scalar_function":
            for statement in node.body:
                if isinstance(statement, ast.Assign):
                    for target in statement.targets:
                        if isinstance(target, ast.Name) and target.id in ("scalar_names", "aggregate_names"):
                            functions[target.id] = sorted(ast.literal_eval(statement.value))
    if set(functions) != {"scalar_names", "aggregate_names"}:
        raise ValueError("Parser function registry layout changed; manual audit required")
    shared_cases = []
    for manifest in sorted((ROOT / "yt-sql/cases").glob("**/test.json")):
        obj = json.loads(manifest.read_text(encoding="utf-8"))
        shared_cases.append(
            {"id": obj["id"], "features": obj.get("features", []), "path": str(manifest.relative_to(ROOT))}
        )
    report = {
        "version": 1,
        "status": "baseline_inventory_not_certified_completeness",
        "sources": {
            "features_and_cases": str(CASES_PATH.relative_to(ROOT)),
            "parser_functions": str(PARSER_PATH.relative_to(ROOT)),
        },
        "registered_features": features,
        "feature_to_existing_cases": {feature: sorted(by_feature.get(feature, [])) for feature in features},
        "existing_cases": sorted(cases, key=lambda x: x["id"]),
        "unregistered_existing_case_tags": sorted(set(by_feature) - set(features)),
        "parser_functions": {"scalar": functions["scalar_names"], "aggregate": functions["aggregate_names"]},
        "shared_cases": shared_cases,
        "coverage_dimensions": [
            "valid_syntax",
            "invalid_syntax",
            "semantics",
            "type_and_null",
            "boundary",
            "interaction",
            "adversarial",
        ],
        "coverage_policy": "A feature is not complete merely because an existing case names it. Each applicable dimension requires reviewed evidence or a documented non-applicability reason.",
    }
    write_or_check(OUTPUT, report, args.check)
    write_or_check(EXISTING_OUTPUT, existing_inventory(features, cases), args.check)


if __name__ == "__main__":
    main()
