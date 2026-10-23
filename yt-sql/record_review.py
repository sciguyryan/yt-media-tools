"""Record an independent semantic review without promoting an expectation.

The reviewer must provide their own rationale and explicit judgement. This tool
checks candidate provenance but cannot determine whether query semantics are right.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from review_candidate import ReviewError, inspect


class RecordError(ValueError):
    """A review record cannot be issued safely."""


def record(
    case: Path,
    candidate: Path,
    destination: Path,
    *,
    reviewer: str,
    rationale: str,
    decision: str,
    root: Path | None = None,
) -> Path:
    """Write a new review record, keeping all normative expectations unchanged."""
    if decision not in {"approve", "reject"}:
        raise RecordError("decision must be approve or reject")
    if not reviewer.strip() or not rationale.strip():
        raise RecordError("reviewer and independent semantic rationale are required")
    try:
        summary = inspect(case, candidate, **({"root": root} if root is not None else {}))
    except ReviewError as exc:
        raise RecordError(str(exc)) from exc
    if decision == "approve" and summary["execution_configuration_provenance"] != "verified-by-re-execution-at-staging":
        raise RecordError("approval requires a configuration-verified version 2 candidate")
    payload = {
        "version": 1,
        "case_id": summary["case_id"],
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "decision": decision,
        "reviewer": reviewer.strip(),
        "rationale": rationale.strip(),
        "independent_semantic_review": True,
        "expectation_promoted": False,
    }
    data = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    try:
        with destination.open("xb") as output:
            output.write(data)
    except FileExistsError as exc:
        raise RecordError("review record already exists; refusing overwrite") from exc
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--decision", required=True, choices=("approve", "reject"))
    args = parser.parse_args()
    try:
        record(
            args.case,
            args.candidate,
            args.destination,
            reviewer=args.reviewer,
            rationale=args.rationale,
            decision=args.decision,
        )
    except (RecordError, OSError) as exc:
        parser.exit(1, f"review recording failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
