#!/usr/bin/env python3
"""Run selectable local quality checks before staging changes.

Checks run from the repository root. Ruff and JSON autofix steps may edit files;
this command never stages or commits changes.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]


def checks() -> list[Check]:
    """Define stable CLI names and the existing repository commands."""
    python = sys.executable
    ruff = ("ruff",)
    config = ("--no-cache", "--config", "./ruff.toml")
    return [
        Check("markdown", ("npm", "run", "lint:markdown")),
        Check("ruff-fix", (*ruff, "check", "--fix", *config, ".")),
        Check("ruff-format", (*ruff, "format", *config, ".")),
        Check("ruff-check", (*ruff, "check", *config, ".")),
        Check("ruff-format-check", (*ruff, "format", *config, "--check", "--diff", ".")),
        Check("json-fix", (python, "scripts/json_quality.py", "--write")),
        Check("json-check", (python, "scripts/json_quality.py")),
        Check("dataset", (python, "yt-sql/export_portable_dataset.py", "--check")),
        Check("topology", (python, "yt-sql/export_portable_topology.py", "--check")),
        Check("facets", (python, "yt-sql/export_portable_facets.py", "--check")),
        Check("coverage", (python, "yt-sql/build_coverage_inventory.py", "--check")),
        Check("unicode-audit", (python, "yt-sql/build_unicode_fixture_audit.py", "--check")),
        Check("sqlite", (python, "-m", "sqlfluff", "lint", "--config", ".sqlfluff", "common/sqlite/statements")),
        Check("grammar", (python, "yt-sql/sqlfluff/audit_grammar.py")),
        Check("ysql-format", (python, "scripts/ytsql_format.py", "check")),
        Check("sqlfluff-tests", (python, "-m", "unittest", "discover", "-s", "yt-sql/sqlfluff", "-p", "test_*.py")),
        Check("python-tests", (python, "run-tests.py", "--python")),
        Check("rust-tests", (python, "run-tests.py", "--rust")),
    ]


def render_table(results: list[tuple[str, str, float]], total: int) -> None:
    """Print a compact ASCII summary that works without colour or Unicode."""
    rows = [(name, status, f"{duration:.1f}s") for name, status, duration in results]
    name_width = max([5, *(len(name) for name, _, _ in rows)])
    width = name_width + 24
    print("\n" + "=" * width)
    print(f"{'Check':<{name_width}}  {'Result':<8}  Duration")
    print("-" * width)
    for name, status, duration in rows:
        print(f"{name:<{name_width}}  {status:<8}  {duration:>8}")
    skipped = total - len(rows)
    if skipped:
        print(f"{'Remaining checks':<{name_width}}  {'SKIPPED':<8}  {skipped:>8}")
    print("=" * width, flush=True)


def execute(check: Check, *, verbose: bool) -> tuple[bool, float, str]:
    """Capture normal output, exposing failure diagnostics and optional live detail."""
    started = time.monotonic()
    try:
        if verbose:
            print("$ " + " ".join(check.command), flush=True)
            completed = subprocess.run(check.command, cwd=ROOT, check=False)
            return completed.returncode == 0, time.monotonic() - started, ""
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as output:
            completed = subprocess.run(check.command, cwd=ROOT, check=False, stdout=output, stderr=subprocess.STDOUT)
            if completed.returncode:
                output.seek(0)
                detail = output.read()
            else:
                detail = ""
            return completed.returncode == 0, time.monotonic() - started, detail
    except OSError as error:
        return False, time.monotonic() - started, str(error)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List available check names and exit")
    parser.add_argument(
        "--only", action="append", metavar="NAME", help="Run one named check; repeat for multiple checks"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show commands and live tool output")
    parser.add_argument("--keep-going", action="store_true", help="Run later checks after failures")
    args = parser.parse_args(arguments)
    available = checks()
    by_name = {check.name: check for check in available}
    if args.list:
        for check in available:
            print(check.name)
        return 0
    if args.only:
        unknown = sorted(set(args.only) - by_name.keys())
        if unknown:
            parser.error("Unknown check(s): " + ", ".join(unknown) + "; use --list")
        selected = [check for check in available if check.name in set(args.only)]
    else:
        selected = available
    if Path.cwd().resolve() != ROOT:
        parser.error("Run this command from the repository root")
    if sys.prefix == sys.base_prefix:
        parser.error("Activate the repository virtual environment first")
    results: list[tuple[str, str, float]] = []
    failed = False
    for index, check in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {check.name} ...", flush=True)
        if check.name == "python-tests":
            try:
                import pytest  # noqa: F401
                import xdist  # noqa: F401
            except ImportError:
                detail = "Python test dependencies are missing from this interpreter. Run: python -m pip install -r python/requirements-test.txt (or install pytest and pytest-xdist into the active venv)."
                passed, duration = False, 0.0
            else:
                passed, duration, detail = execute(check, verbose=args.verbose)
        else:
            passed, duration, detail = execute(check, verbose=args.verbose)
        status = "PASS" if passed else "FAIL"
        results.append((check.name, status, duration))
        print(f"  {status} ({duration:.1f}s)", flush=True)
        if not passed:
            failed = True
            if detail:
                print("\n" + detail.rstrip() + "\n", file=sys.stderr, flush=True)
            if not args.keep_going:
                break
    render_table(results, len(selected))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
