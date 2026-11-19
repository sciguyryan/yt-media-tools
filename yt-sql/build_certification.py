"""Certify the YT-SQL portable corpus for cross-implementation conformance.

Phase 6.6 takes option (a): the corpus is certified modulo explicitly deferred
features. Every coverage cell must be either reviewed with cited admitted cases
or explicitly deferred with a recorded justification; silent gaps block
certification. The certified subset is the normative target for Phase 7
cross-implementation adapters.
"""

from __future__ import annotations

import argparse
import json

import build_coverage_gap_matrix
from run_conformance import HarnessError, run
from validate_corpus import ROOT, CorpusError, validate_corpus

OUTPUT = ROOT / "CERTIFICATION.json"
EVIDENCE = ROOT / "COVERAGE-EVIDENCE.json"
OVERRIDES = ROOT / "expectations/python.json"

# Bump when re-certifying after material corpus or evidence changes.
CERTIFIED_ON = "2026-11-19"
REVIEWER = "GLM-5.3-Flash assisted session (OpenCode), on behalf of the repository maintainer"

GATE = (
    (
        "corpus_valid",
        "Every corpus case validates structurally and every declared xfail names an admitted case.",
    ),
    (
        "conformance_clean",
        "The Python candidate reproduces every approved expectation; only declared xfails may deviate.",
    ),
    (
        "functions_fully_reviewed",
        "Every coverage-dimension cell of every registered function carries reviewed evidence.",
    ),
    (
        "feature_cells_adjudicated",
        "Every feature cell is reviewed or explicitly deferred with a recorded justification.",
    ),
    (
        "gap_matrix_current",
        "COVERAGE-GAP-MATRIX.json matches its generator.",
    ),
)


def _corpus_counts() -> dict[str, int]:
    normative = torture = 0
    for path in (ROOT / "cases").rglob("test.json"):
        if "torture-portable" in path.parts:
            torture += 1
        else:
            normative += 1
    return {"cases": normative + torture, "normative": normative, "torture": torture}


def _coverage(matrix: dict[str, object]) -> tuple[dict[str, object], list[str]]:
    """Summarise reviewed and deferred cells; return (summary, unadjudicated keys)."""
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {"cells": {}}
    cells = evidence.get("cells", {})

    def collect(section: str, prefix: str, name_field: str) -> tuple[dict[str, int], list[dict[str, object]], list[str]]:
        total = reviewed = 0
        deferred: list[dict[str, object]] = []
        unadjudicated: list[str] = []
        for entry in matrix[section]:
            name = entry[name_field]
            deferred_dimensions: dict[str, str] = {}
            for dimension, record in entry["dimensions"].items():
                total += 1
                if record["status"] == "reviewed":
                    reviewed += 1
                    continue
                justification = cells.get(prefix + name, {}).get("dimensions", {}).get(dimension, {}).get("justification")
                if not justification:
                    unadjudicated.append(f"{prefix}{name}/{dimension}")
                else:
                    deferred_dimensions[dimension] = justification
            if deferred_dimensions:
                deferred.append({"feature": name, "deferred_dimensions": deferred_dimensions})
        summary = {"total": total, "reviewed": reviewed, "deferred": total - reviewed}
        return summary, deferred, unadjudicated

    function_summary, _, _ = collect("functions", "function:", "name")
    feature_summary, deferred_features, unadjudicated = collect("registered_features", "feature:", "feature")
    coverage: dict[str, object] = {
        "total_cells": function_summary["total"] + feature_summary["total"],
        "reviewed_cells": function_summary["reviewed"] + feature_summary["reviewed"],
        "deferred_cells": function_summary["deferred"] + feature_summary["deferred"],
        "function_cells": function_summary,
        "feature_cells": feature_summary,
        "deferred_features": deferred_features,
    }
    return coverage, unadjudicated


def generate() -> dict[str, object]:
    conditions: list[dict[str, object]] = []

    corpus_counts: dict[str, int] = {}
    corpus_ok = True
    try:
        count = validate_corpus(ROOT)
        corpus_counts = {**_corpus_counts(), "validated": count}
    except CorpusError as exc:
        corpus_ok = False
        corpus_counts = {"error": str(exc)}
    conditions.append({"condition": GATE[0][0], "description": GATE[0][1], "satisfied": corpus_ok})

    conformance: dict[str, object] = {}
    conformance_ok = False
    try:
        report = run(root=ROOT, implementation="python", configuration="default")
        counts = report["counts"]
        conformance = {
            "implementation": report["implementation"],
            "configuration": report["configuration"],
            "counts": counts,
            "non_passing_cases": sorted(r["id"] for r in report["results"] if r["status"] != "pass"),
        }
        overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))["expectations"]
        conformance["declared_xfails"] = sorted(overrides)
        conformance_ok = counts["fail"] == 0 and counts["error"] == 0 and counts["xpass"] == 0
    except (HarnessError, CorpusError) as exc:
        conformance = {"error": str(exc)}
        conformance["declared_xfails"] = []
        conformance["non_passing_cases"] = []
    conditions.append({"condition": GATE[1][0], "description": GATE[1][1], "satisfied": conformance_ok})

    matrix = build_coverage_gap_matrix.generate()
    coverage, unadjudicated = _coverage(matrix)
    functions_ok = coverage["function_cells"]["reviewed"] == coverage["function_cells"]["total"]
    conditions.append({"condition": GATE[2][0], "description": GATE[2][1], "satisfied": functions_ok})
    features_ok = not unadjudicated
    conditions.append(
        {
            "condition": GATE[3][0],
            "description": GATE[3][1],
            "satisfied": features_ok,
            "unadjudicated_cells": unadjudicated,
        }
    )

    matrix_ok = _matrix_current()
    conditions.append({"condition": GATE[4][0], "description": GATE[4][1], "satisfied": matrix_ok})

    status = "certified" if all(c["satisfied"] for c in conditions) else "not_certified"
    return {
        "version": 1,
        "status": status,
        "certified_on": CERTIFIED_ON,
        "reviewer": REVIEWER,
        "scope": "Phase 6.6: the portable corpus is certified modulo explicitly deferred features",
        "corpus": corpus_counts,
        "conformance": conformance,
        "coverage": coverage,
        "gate": conditions,
    }


def _matrix_current() -> bool:
    try:
        content = json.dumps(build_coverage_gap_matrix.generate(), indent=2, ensure_ascii=False) + "\n"
    except Exception:  # noqa: BLE001 - any drift or invalid evidence leaves the gate unsatisfied
        return False
    gap_matrix = ROOT / "COVERAGE-GAP-MATRIX.json"
    return gap_matrix.exists() and gap_matrix.read_text(encoding="utf-8") == content


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the committed certification without writing")
    args = parser.parse_args()
    content = json.dumps(generate(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            raise SystemExit("CERTIFICATION.json is stale or the certification gate no longer holds; regenerate it")
        print("CERTIFICATION.json is current")
    else:
        OUTPUT.write_text(content, encoding="utf-8")
        print(f"Updated CERTIFICATION.json ({json.loads(content)['status']})")


if __name__ == "__main__":
    main()
