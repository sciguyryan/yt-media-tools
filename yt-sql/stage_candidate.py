"""Stage an observed Python outcome for review without changing corpus expectations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from compare_outcomes import OutcomeError, _validate
from validate_corpus import CorpusError, _load, validate_case

ROOT = Path(__file__).resolve().parent


class CandidateError(ValueError):
    """A candidate cannot be staged safely."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def stage(
    case: Path, observed: Path, destination: Path, *, root: Path = ROOT, configuration: str | None = None
) -> Path:
    """Write a new, explicitly provisional candidate; never overwrite an existing file."""
    case = case.resolve()
    try:
        case.relative_to((root / "cases").resolve())
    except ValueError as exc:
        raise CandidateError("case must be inside the corpus cases directory") from exc
    try:
        case_id = validate_case(case, root=root, allow_missing_expected=True)
        manifest = _load(case / "test.json")
        outcome = _validate(_load(observed))
        query_bytes = (case / "query.ysql").read_bytes()
        dataset_digests = {
            name: _digest((root / "datasets" / f"{name}.json").read_bytes()) for name in manifest["datasets"]
        }
        # A configuration label alone is not evidence that the observation was
        # produced with those settings. Re-execute before recording provenance.
        if configuration is not None:
            from run_python_candidate import AdapterError, observe

            try:
                actual = observe(case, configuration=configuration, root=root)
            except AdapterError as exc:
                raise CandidateError(f"cannot verify execution configuration: {exc}") from exc
            if actual != outcome:
                raise CandidateError("observation differs from independently re-executed configuration")
            configs = manifest.get("execution", {}).get("configurations", [{"id": "default", "settings": {}}])
            selected = next(entry for entry in configs if entry["id"] == configuration)
        candidate = {
            "version": 1,
            "status": "provisional",
            "case_id": case_id,
            "implementation": "python",
            "query_sha256": _digest(query_bytes),
            "manifest_sha256": _digest((case / "test.json").read_bytes()),
            "datasets_sha256": dataset_digests,
            "observed": outcome,
        }
        if configuration is not None:
            candidate["version"] = 2
            candidate["execution_configuration"] = selected
        data = _canonical(candidate)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(data)
    except (CorpusError, OutcomeError, OSError, ValueError) as exc:
        if isinstance(exc, FileExistsError):
            raise CandidateError("candidate destination already exists; refusing overwrite") from exc
        raise CandidateError(str(exc)) from exc
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path, help="Case directory beneath yt-sql/cases")
    parser.add_argument("observed", type=Path, help="JSON outcome captured by a Python adapter")
    parser.add_argument("destination", type=Path, help="New provisional candidate JSON file")
    parser.add_argument("--configuration", help="Verify the observation by re-executing this configuration")
    args = parser.parse_args()
    try:
        path = stage(args.case, args.observed, args.destination, configuration=args.configuration)
    except CandidateError as exc:
        parser.exit(1, f"candidate staging failed: {exc}\n")
    print(f"Staged provisional candidate: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
