"""Promote an independently approved candidate with explicit replacement consent.

Promotion is intentionally conservative: existing normative expectations may only
be replaced with an explicit flag, and the existing bytes are retained separately.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from compare_outcomes import _validate
from approval_evidence import approved_observation


class PromotionError(ValueError):
    """A candidate cannot be promoted safely."""


def promote(case: Path, candidate: Path, review: Path, *, replace: bool = False, root: Path | None = None) -> Path:
    """Promote an approved observation, retaining the previous expectation on replacement."""
    try:
        observed = _validate(approved_observation(case, candidate, review, root=root))
        destination = case / "expected.json"
        backup = case / "expected.json.before-promotion"
        temporary = case / "expected.json.promotion-tmp"
        # Initial admission has a separate review boundary. In particular, do
        # not create a new normative file while using replacement semantics.
        if not destination.is_file() or destination.is_symlink():
            raise PromotionError("existing regular expected.json required; use new-case admission instead")
        if not replace:
            raise PromotionError("existing expectation requires explicit --replace")
        # Refuse stale artefacts before making any writes. A pre-existing backup
        # may represent an earlier promotion and must never be reused.
        if backup.exists() or backup.is_symlink():
            raise PromotionError("previous expectation backup already exists")
        if temporary.exists() or temporary.is_symlink():
            raise PromotionError("promotion temporary file already exists")
        previous = destination.read_bytes()
        rendered = (json.dumps(observed, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
        backup_created = False
        try:
            # Prepare and sync the replacement before writing the recovery copy.
            # The final rename is atomic on the same filesystem.
            with temporary.open("xb") as stream:
                stream.write(rendered)
                stream.flush()
                os.fsync(stream.fileno())
            with backup.open("xb") as stream:
                backup_created = True
                stream.write(previous)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except BaseException:
            temporary.unlink(missing_ok=True)
            if backup_created:
                backup.unlink(missing_ok=True)
            raise
        return destination
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if isinstance(exc, PromotionError):
            raise
        raise PromotionError(str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("review", type=Path)
    parser.add_argument("--replace", action="store_true", help="Explicitly replace the existing normative expectation")
    args = parser.parse_args()
    try:
        destination = promote(args.case, args.candidate, args.review, replace=args.replace)
    except PromotionError as exc:
        parser.exit(1, f"promotion refused: {exc}\n")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
