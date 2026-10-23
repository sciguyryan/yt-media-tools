"""Validate the stable version 1 conformance report contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

STATUSES = ("pass", "fail", "error", "xfail", "xpass")


class ReportError(ValueError):
    """A generated conformance report violates the portable contract."""


def validate_report(report: object) -> dict[str, object]:
    """Check report shape, ordering and internally consistent counts."""
    if not isinstance(report, dict) or set(report) != {
        "version",
        "implementation",
        "configuration",
        "results",
        "counts",
    }:
        raise ReportError("report must contain exactly the version 1 report fields")
    if type(report["version"]) is not int or report["version"] != 1:
        raise ReportError("unsupported report version")
    for field in ("implementation", "configuration"):
        if not isinstance(report[field], str) or not report[field].strip():
            raise ReportError(f"{field} must be a non-empty string")
    results = report["results"]
    if not isinstance(results, list):
        raise ReportError("results must be an array")
    ids: list[str] = []
    actual_counts = dict.fromkeys(STATUSES, 0)
    for index, item in enumerate(results):
        if not isinstance(item, dict) or set(item) != {"id", "status", "detail"}:
            raise ReportError(f"result {index} has invalid fields")
        case_id, status, detail = item["id"], item["status"], item["detail"]
        if not isinstance(case_id, str) or not case_id.strip():
            raise ReportError(f"result {index} has an invalid case ID")
        if not isinstance(status, str) or status not in STATUSES:
            raise ReportError(f"result {index} has an invalid status")
        if not isinstance(detail, str):
            raise ReportError(f"result {index} has an invalid detail")
        ids.append(case_id)
        actual_counts[status] += 1
    if ids != sorted(set(ids)):
        raise ReportError("case IDs must be unique and sorted")
    counts = report["counts"]
    if not isinstance(counts, dict) or set(counts) != set(STATUSES):
        raise ReportError("counts must contain exactly the five status fields")
    if any(type(counts[name]) is not int or counts[name] < 0 for name in STATUSES):
        raise ReportError("counts must be non-negative integers")
    if counts != actual_counts:
        raise ReportError("counts do not agree with results")
    return report


def load_report(path: Path) -> dict[str, object]:
    """Reject duplicate JSON keys and malformed report structures."""

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ReportError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        report = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"invalid JSON report: {exc}") from exc
    return validate_report(report)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        report = load_report(args.report)
    except (OSError, ReportError) as exc:
        parser.exit(2, f"Invalid conformance report: {exc}\n")
    print(f"Valid conformance report: {len(report['results'])} case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
