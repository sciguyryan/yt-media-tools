"""Conservative YT-SQL formatting gate using Discover's authoritative parser.

No file is modified unless the formatted result passes all safety checks.
"""

import argparse
import dataclasses
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

from yt_media_tools.query_parser import parse_query  # noqa: E402


# These fields describe the spelling or location of a parsed expression, not
# its semantic structure. Keep raw literal spelling, operators and identifiers.
_LOCATION_FIELDS = {"source", "position", "span", "start_position", "end_position"}


def structural_tree(value: object) -> object:
    """Compare parsed trees without layout-dependent source positions."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__name__,
            tuple(
                (field.name, structural_tree(getattr(value, field.name)))
                for field in dataclasses.fields(value)
                if field.name not in _LOCATION_FIELDS
            ),
        )
    if isinstance(value, (tuple, list)):
        return tuple(structural_tree(item) for item in value)
    if isinstance(value, dict):
        return tuple(sorted((key, structural_tree(item)) for key, item in value.items()))
    return value


def format_checked(source: str) -> str:
    """Return a verified formatted query or raise without changing the input."""
    original_tree = structural_tree(parse_query(source))

    def invoke(command: str, query: str) -> str:
        result = subprocess.run(
            [sys.executable, str(HERE / "run.py"), command, "--config", str(ROOT / ".sqlfluff-ysql"), "-"],
            cwd=ROOT,
            input=query,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or (
            command == "parse" and any(marker in result.stdout.lower() for marker in ("unparsable:", "unlexable:"))
        ):
            raise ValueError(f"SQLFluff {command} failed: {(result.stderr + result.stdout)[-1200:]}")
        return result.stdout

    invoke("parse", source)
    formatted = invoke("format", source)
    invoke("parse", formatted)

    # The AST does not retain comments. Preserve their exact spelling and order
    # separately, including inline comments; reject ambiguous rewrites.
    def comments(text: str) -> list[str]:
        return re.findall(r"#[^\r\n]*", text)

    if comments(source) != comments(formatted):
        raise ValueError("Formatting changed or removed query comments")
    if structural_tree(parse_query(formatted)) != original_tree:
        raise ValueError("Formatting changed the authoritative YT-SQL parse tree")
    if invoke("format", formatted) != formatted:
        raise ValueError("SQLFluff formatting is not idempotent")
    return formatted


def _show_progress(completed: int, total: int, *, stream: object, interactive: bool) -> None:
    """Render one bounded progress line without polluting redirected output."""
    if not interactive:
        return
    width = 28
    filled = width * completed // total
    bar = "#" * filled + "-" * (width - filled)
    print(f"\rYT-SQL [{bar}] {completed}/{total} ({completed * 100 // total}%)", end="", file=stream, flush=True)
    if completed == total:
        print(file=stream, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help=".ysql files or directories (default: yt-sql/cases)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--check", action="store_true", help="Fail if any query needs formatting")
    action.add_argument("--write", action="store_true", help="Write only after every file passes validation")
    args = parser.parse_args(argv)
    targets = args.paths or [ROOT / "yt-sql/cases"]
    paths = sorted({file for path in targets for file in (path.rglob("*.ysql") if path.is_dir() else (path,))})
    if not paths or any(path.suffix != ".ysql" or not path.is_file() for path in paths):
        parser.error("Provide existing .ysql files or directories containing them")
    changes = {}
    interactive = sys.stderr.isatty() and os.environ.get("CI", "").lower() not in {"1", "true", "yes"}
    _show_progress(0, len(paths), stream=sys.stderr, interactive=interactive)
    for index, path in enumerate(paths, start=1):
        try:
            original = path.read_text(encoding="utf-8")
            formatted = format_checked(original)
            if original != formatted:
                changes[path] = formatted
        except (ValueError, OSError, RuntimeError) as exc:
            if interactive:
                print(file=sys.stderr)
            print(f"Formatting blocked for {path}: {exc}", file=sys.stderr)
            return 1
        _show_progress(index, len(paths), stream=sys.stderr, interactive=interactive)
    # Validate every target before writing any of them. This is not a
    # transactional filesystem operation; unexpected I/O errors can still occur.
    if args.write:
        for path, content in changes.items():
            path.write_text(content, encoding="utf-8")
    print(f"Checked {len(paths)} .ysql files; {len(changes)} would change" + (" (written)" if args.write else ""))
    if args.check and changes:
        for path in changes:
            print(f"Needs formatting: {path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
