"""Check a provisional candidate's provenance before independent semantic review.

This tool never approves an observation or changes a normative expectation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from compare_outcomes import OutcomeError, _validate, outcomes_match
from validate_corpus import CorpusError, _load, validate_case

ROOT = Path(__file__).resolve().parent


class ReviewError(ValueError):
    """The candidate cannot safely be considered for semantic review."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect(case: Path, candidate_path: Path, *, root: Path = ROOT) -> dict[str, object]:
    """Return a non-approving review summary after verifying available evidence."""
    case = case.resolve()
    try:
        case.relative_to((root / "cases").resolve())
        case_id = validate_case(case, root=root, allow_missing_expected=True)
        manifest = _load(case / "test.json")
        candidate = _load(candidate_path)
        common = {
            "version",
            "status",
            "case_id",
            "implementation",
            "query_sha256",
            "manifest_sha256",
            "datasets_sha256",
            "observed",
        }
        if not isinstance(candidate, dict) or type(candidate.get("version")) is not int:
            raise ReviewError("unsupported provisional candidate shape")
        version = candidate["version"]
        required = common | ({"execution_configuration"} if version == 2 else set())
        if version not in (1, 2) or set(candidate) != required:
            raise ReviewError("unsupported provisional candidate shape")
        if (
            candidate["status"] != "provisional"
            or candidate["case_id"] != case_id
            or candidate["implementation"] != "python"
        ):
            raise ReviewError("candidate identity or provisional status does not match")
        if version == 2:
            configs = manifest.get("execution", {}).get("configurations", [{"id": "default", "settings": {}}])
            if candidate["execution_configuration"] not in configs:
                raise ReviewError("execution configuration does not match current manifest")
        if candidate["query_sha256"] != _digest(case / "query.ysql"):
            raise ReviewError("query digest mismatch")
        if candidate["manifest_sha256"] != _digest(case / "test.json"):
            raise ReviewError("manifest digest mismatch")
        digests = {name: _digest(root / "datasets" / f"{name}.json") for name in manifest["datasets"]}
        if candidate["datasets_sha256"] != digests:
            raise ReviewError("dataset digest mismatch")
        observed = _validate(candidate["observed"])
        expected_path = case / "expected.json"
        if expected_path.exists() or expected_path.is_symlink():
            expected = _validate(_load(expected_path))
            matches = outcomes_match(
                expected, observed, order=manifest["order"], group_sizes=manifest.get("group_sizes")
            )
        else:
            matches = None
        return {
            "case_id": case_id,
            "provenance": "file-digests-verified",
            "observation_matches_current_expected": matches,
            "semantic_review": "required",
            "approval": "not-granted",
            "execution_configuration_provenance": (
                "verified-by-re-execution-at-staging" if version == 2 else "not-recorded-in-v1-candidate"
            ),
        }
    except (CorpusError, OutcomeError, OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, ReviewError):
            raise
        raise ReviewError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.case, args.candidate)
    except ReviewError as exc:
        parser.exit(1, f"candidate review preflight failed: {exc}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
