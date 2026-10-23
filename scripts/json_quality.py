"""Strict JSON lint and formatting check for tracked repository JSON files.

Formatting follows the existing Python generators: two spaces, UTF-8 Unicode,
no key sorting, and one terminal newline. Use --write for deliberate edits.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def validate_unicode(value: object) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise ValueError("unpaired Unicode surrogate")
    elif isinstance(value, list):
        for item in value:
            validate_unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            validate_unicode(key)
            validate_unicode(item)


def tracked_json() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.json"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode == 0:
        return sorted(
            candidate
            for path in result.stdout.split(b"\0")
            if path
            if (candidate := ROOT / path.decode("utf-8")).is_file()
        )
    # Release archives have no .git directory; check their entire source tree.
    return sorted(
        path
        for path in ROOT.rglob("*.json")
        if not any(part in {".git", "node_modules", ".venv"} for part in path.relative_to(ROOT).parts)
    )


def check_file(path: Path, *, write: bool, format_check: bool) -> str | None:
    try:
        original = path.read_text(encoding="utf-8-sig")
        value = json.loads(original, object_pairs_hook=unique_pairs, parse_constant=reject_constant)
        validate_unicode(value)
        formatted = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        if format_check and original != formatted:
            if write:
                path.write_text(formatted, encoding="utf-8")
            else:
                return "format differs (run python scripts/json_quality.py --write)"
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        return str(error)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Rewrite JSON to canonical formatting")
    parser.add_argument("--lint-only", action="store_true", help="Check validity without enforcing formatting")
    parser.add_argument("paths", nargs="*", type=Path, help="Explicit JSON paths (otherwise tracked files)")
    args = parser.parse_args()
    if args.write and args.lint_only:
        parser.error("--write and --lint-only cannot be combined")
    paths = [path if path.is_absolute() else ROOT / path for path in args.paths] if args.paths else tracked_json()
    failures = 0
    for path in paths:
        error = check_file(path, write=args.write, format_check=not args.lint_only)
        if error:
            print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {error}", file=sys.stderr)
            failures += 1
    print(f"Checked {len(paths)} JSON files; {failures} failed")
    return int(failures != 0)


if __name__ == "__main__":
    raise SystemExit(main())
