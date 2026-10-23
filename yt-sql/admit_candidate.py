"""Admit a new case expectation after independent review and explicit consent."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from compare_outcomes import _validate
from promote_candidate import PromotionError
from approval_evidence import approved_observation


def admit(case: Path, candidate: Path, review: Path, *, root: Path | None = None) -> Path:
    """Create only a missing expectation; never replace or repair existing files."""
    try:
        observed = approved_observation(case, candidate, review, root=root)
        destination = case / "expected.json"
        temporary = case / "expected.json.promotion-tmp"
        backup = case / "expected.json.before-promotion"
        if destination.exists() or destination.is_symlink():
            raise PromotionError("expectation already exists; admission cannot replace it")
        if temporary.exists() or temporary.is_symlink() or backup.exists() or backup.is_symlink():
            raise PromotionError("stale promotion artefacts require manual inspection")
        rendered = (json.dumps(_validate(observed), indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode(
            "utf-8"
        )
        # Publish only complete bytes. A hard link fails if another process
        # has already created the destination, without replacing its content.
        with temporary.open("xb") as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
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
    args = parser.parse_args()
    try:
        result = admit(args.case, args.candidate, args.review)
    except PromotionError as exc:
        parser.exit(1, f"admission refused: {exc}\n")
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
