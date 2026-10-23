"""Validate review attestations shared by admission and replacement promotion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from review_candidate import inspect


class ApprovalError(ValueError):
    """The candidate lacks current, matching independent approval evidence."""


_FIELDS = {
    "version",
    "case_id",
    "candidate_sha256",
    "decision",
    "reviewer",
    "rationale",
    "independent_semantic_review",
    "expectation_promoted",
}


def approved_observation(case: Path, candidate: Path, review: Path, *, root: Path | None = None) -> dict:
    """Return an approved observation after checking provenance and review evidence."""
    summary = inspect(case, candidate, **({"root": root} if root is not None else {}))
    staged = json.loads(candidate.read_text(encoding="utf-8"))
    attestation = json.loads(review.read_text(encoding="utf-8"))
    if (
        not isinstance(attestation, dict)
        or set(attestation) != _FIELDS
        or type(attestation["version"]) is not int
        or attestation["version"] != 1
        or attestation["case_id"] != summary["case_id"]
        or attestation["candidate_sha256"] != hashlib.sha256(candidate.read_bytes()).hexdigest()
        or attestation["decision"] != "approve"
        or attestation["independent_semantic_review"] is not True
        or attestation["expectation_promoted"] is not False
        or not isinstance(attestation["reviewer"], str)
        or not attestation["reviewer"].strip()
        or not isinstance(attestation["rationale"], str)
        or not attestation["rationale"].strip()
    ):
        raise ApprovalError("review approval or candidate digest does not match")
    if (
        type(staged["version"]) is not int
        or staged["version"] != 2
        or summary["execution_configuration_provenance"] != "verified-by-re-execution-at-staging"
    ):
        raise ApprovalError("verified version 2 candidate required")
    return staged["observed"]
