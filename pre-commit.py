#!/usr/bin/env python3
"""Run selectable local quality checks before staging changes.

Checks run from the repository root. Ruff and JSON autofix steps may edit files;
this command never stages or commits changes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "pre-commit" / "results.json"
PYTEST_REPORT = ROOT / ".cache" / "pre-commit" / "pytest-results.json"


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


def execute(
    check: Check,
    *,
    verbose: bool,
    command_override: tuple[str, ...] | None = None,
    env_override: dict[str, str] | None = None,
) -> tuple[bool, float, str]:
    """Capture normal output, exposing failure diagnostics and optional live detail."""
    started = time.monotonic()
    command = command_override or check.command
    try:
        if verbose:
            print("$ " + " ".join(command), flush=True)
            completed = subprocess.run(command, cwd=ROOT, check=False, env=env_override)
            return completed.returncode == 0, time.monotonic() - started, ""
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as output:
            completed = subprocess.run(
                command, cwd=ROOT, check=False, stdout=output, stderr=subprocess.STDOUT, env=env_override
            )
            output.seek(0)
            detail = output.read() if completed.returncode or check.name == "rust-tests" else ""
            return completed.returncode == 0, time.monotonic() - started, detail
    except OSError as error:
        return False, time.monotonic() - started, str(error)


def load_cache() -> dict:
    """Treat malformed or outdated cache content as absent, never as success."""
    try:
        data = json.loads(CACHE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("version") == 1 and isinstance(data.get("checks"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"version": 1, "checks": {}}


def save_cache(data: dict) -> None:
    """Replace local state atomically so interruptions retain the last complete update."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CACHE.parent, delete=False) as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(CACHE)


def rust_outcomes(output: str) -> dict[str, str]:
    """Extract named Rust test results; a build failure has no individual test IDs."""
    matches = re.findall(r"^test (.+) \.\.\. (ok|FAILED|ignored)$", output, re.MULTILINE)
    return {name: {"ok": "PASS", "FAILED": "FAIL", "ignored": "SKIPPED"}[status] for name, status in matches}


def cached_failures(entry: dict) -> list[str]:
    return sorted(name for name, status in entry.get("tests", {}).items() if status == "FAIL")


def test_command(check: Check, failures: list[str] | None) -> tuple[str, ...]:
    if check.name == "python-tests":
        command = (*check.command, "-p", "scripts.precommit_pytest_report")
        return (*command, *(failures or ()))
    if check.name == "rust-tests" and failures:
        # Cargo accepts a single name filter per invocation; each failure is a separate command.
        return (*check.command,)
    return check.command


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List available check names and exit")
    parser.add_argument(
        "--only", action="append", metavar="NAME", help="Run one named check; repeat for multiple checks"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show commands and live tool output")
    parser.add_argument("--keep-going", action="store_true", help="Run later checks after failures")
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Replay failed checks and individual failed tests from the last recorded run",
    )
    parser.add_argument("--results", action="store_true", help="Show cached per-test outcomes without executing checks")
    args = parser.parse_args(arguments)
    available = checks()
    by_name = {check.name: check for check in available}
    if args.results:
        cached = load_cache()
        for name, entry in sorted(cached["checks"].items()):
            tests = entry.get("tests", {})
            if tests:
                print(f"\n{name}: {entry['status']}")
                for nodeid, status in sorted(tests.items()):
                    print(f"  {status:<8} {nodeid}")
            else:
                print(f"{name}: {entry['status']}")
        return 0
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
    cache = load_cache()
    if args.failed_only:
        selected = [check for check in selected if cache["checks"].get(check.name, {}).get("status") == "FAIL"]
        if not selected:
            print("No recorded failures match the selected checks. Run the full gate to validate current code.")
            return 0
    results: list[tuple[str, str, float]] = []
    failed = False
    for index, check in enumerate(selected, 1):
        print(f"[{index}/{len(selected)}] {check.name} ...", flush=True)
        previous = cache["checks"].get(check.name, {})
        failures = cached_failures(previous) if args.failed_only else []
        detail = ""
        outcomes: dict[str, str] = {}
        if check.name == "python-tests":
            try:
                import pytest  # noqa: F401
                import xdist  # noqa: F401
            except ImportError:
                passed, duration = False, 0.0
                detail = (
                    "Python test dependencies are missing. Install python/requirements-test.txt in the active venv."
                )
            else:
                PYTEST_REPORT.unlink(missing_ok=True)
                env = dict(os.environ, YT_PRECOMMIT_PYTEST_REPORT=str(PYTEST_REPORT))
                passed, duration, detail = execute(
                    check,
                    verbose=args.verbose,
                    command_override=test_command(check, failures if failures else None),
                    env_override=env,
                )
                if PYTEST_REPORT.exists():
                    try:
                        outcomes = json.loads(PYTEST_REPORT.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
        elif check.name == "rust-tests" and failures:
            # Run each fully qualified test name independently to avoid a broad filter.
            passed, duration = True, 0.0
            for name in failures:
                command = ("cargo", "test", "--workspace", name, "--", "--exact")
                rust_check = Check(check.name, command)
                ok, elapsed, output = execute(rust_check, verbose=args.verbose)
                duration += elapsed
                passed &= ok
                outcomes[name] = "PASS" if ok else "FAIL"
                detail += output
        else:
            passed, duration, detail = execute(check, verbose=args.verbose)
            if check.name == "rust-tests" and detail:
                outcomes = rust_outcomes(detail)
        # Retain previous individual outcomes for tests not executed by a failed-only replay.
        if args.failed_only and check.name in ("python-tests", "rust-tests"):
            outcomes = {**previous.get("tests", {}), **outcomes}
        cache["checks"][check.name] = {
            "status": "PASS" if passed else "FAIL",
            "duration_seconds": round(duration, 3),
            "tests": outcomes,
        }
        save_cache(cache)
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
