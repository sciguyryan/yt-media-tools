"""Check portable conformance parity across independent CI environments.

All participating environments must execute the same approved case set. A
passing baseline cannot conceal another environment's failure or XFAIL.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from validate_report import ReportError, load_report


class ParityError(ValueError):
    """Conformance reports cannot establish cross-environment parity."""


def compare_reports(paths: list[Path]) -> dict[str, object]:
    """Compare validated reports without treating failure agreement as success."""
    if len(paths) < 2:
        raise ParityError("at least two independent environment reports are required")
    environments: dict[str, dict[str, object]] = {}
    for path in paths:
        report = load_report(path)
        # CI artifact names encode the environment; the report itself identifies
        # implementation and configuration, which must agree across platforms.
        label = path.parent.name
        if label in environments:
            raise ParityError(f"duplicate environment label: {label}")
        environments[label] = report
    labels = sorted(environments)
    baseline = environments[labels[0]]
    expected_ids = {item["id"] for item in baseline["results"]}
    problems: list[str] = []
    baseline_status = {item["id"]: item["status"] for item in baseline["results"]}
    for label in labels:
        report = environments[label]
        if (report["implementation"], report["configuration"]) != (
            baseline["implementation"],
            baseline["configuration"],
        ):
            problems.append(f"{label}: implementation/configuration differs")
        observed = {item["id"]: item["status"] for item in report["results"]}
        if set(observed) != expected_ids:
            missing = sorted(expected_ids - set(observed))
            extra = sorted(set(observed) - expected_ids)
            problems.append(f"{label}: case-set mismatch: missing={missing}, extra={extra}")
        for case_id, status in sorted(observed.items()):
            if status != "pass":
                problems.append(f"{label}: {case_id}: {status}")
            if case_id in baseline_status and status != baseline_status[case_id]:
                problems.append(f"{label}: {case_id}: differs from baseline status")
    return {
        "version": 1,
        "environments": labels,
        "cases": len(expected_ids),
        "passed": not problems,
        "problems": sorted(set(problems)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    try:
        result = compare_reports(args.reports)
    except (OSError, ReportError, ParityError) as exc:
        parser.exit(2, f"Invalid platform comparison: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
