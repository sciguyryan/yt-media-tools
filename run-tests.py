#!/usr/bin/env python3
"""Run the selected Python and Rust test suites from the repository root."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
SUITES = ("python", "rust")


def parse_arguments(arguments: list[str]) -> tuple[argparse.Namespace, list[str]]:
    """Parse suite selection while preserving pytest-specific arguments."""
    parser = argparse.ArgumentParser(
        description="Run the Python and Rust test suites (both by default).",
        epilog="Unrecognised arguments are forwarded to pytest when Python is selected.",
    )
    parser.add_argument("--python", action="store_true", help="Run the Python pytest suite")
    parser.add_argument(
        "--rust", action="store_true", help="Run the Rust workspace tests and the portable corpus conformance"
    )
    parser.add_argument("--list", action="store_true", help="List available test suites and exit")
    parser.add_argument("--serial", action="store_true", help="Disable pytest-xdist parallel execution")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failing suite")
    selected, passthrough = parser.parse_known_args(arguments)
    if passthrough and not selected.python and selected.rust:
        parser.error("pytest arguments require the Python suite; add --python")
    if selected.serial and selected.rust and not selected.python:
        parser.error("--serial applies only to the Python suite; add --python")
    return selected, passthrough


def run_rust_suite() -> int:
    """Run the Rust quality suite: workspace tests plus the portable corpus gate.

    The Rust conformance run is part of the suite, not an optional extra: the
    crate implements the certified language surface, so the committed corpus is
    its behavioural specification. The binary the pytest adapter smoke test
    looks for is built here first.
    """
    cargo = ["cargo", "--locked"]
    commands = [
        (["test", "--workspace", "--all-targets", "--locked"], "Rust workspace tests"),
        (["build", "--workspace", "--all-targets", "--locked"], "Rust build"),
    ]
    for arguments, label in commands:
        print(f"\n=== {label} ===", flush=True)
        try:
            status = subprocess.call(cargo + arguments, cwd=ROOT / "rust")
        except FileNotFoundError as error:
            print(f"rust: required executable is unavailable: {error.filename}", file=sys.stderr)
            return 127
        except OSError as error:
            print(f"rust: unable to start cargo: {error}", file=sys.stderr)
            return 1
        if status:
            return status
    print("\n=== Rust portable conformance ===", flush=True)
    try:
        return subprocess.call(
            [sys.executable, str(ROOT / "yt-sql" / "run_conformance.py"), "--implementation", "rust"],
            cwd=ROOT,
        )
    except OSError as error:
        print(f"rust: unable to start the conformance runner: {error}", file=sys.stderr)
        return 1


def run_suite(name: str, *, serial: bool, pytest_arguments: list[str]) -> int:
    """Execute a native test runner and return its process status."""
    if name == "python":
        command = [sys.executable, str(ROOT / "python" / "run-tests.py")]
        if serial:
            command.append("--serial")
        command.extend(pytest_arguments)
        cwd = ROOT
    else:
        return run_rust_suite()
    print(f"\n=== {name.upper()} TESTS ===", flush=True)
    try:
        return subprocess.call(command, cwd=cwd)
    except FileNotFoundError as error:
        print(f"{name}: required executable is unavailable: {error.filename}", file=sys.stderr)
        return 127
    except OSError as error:
        print(f"{name}: unable to start tests: {error}", file=sys.stderr)
        return 1


def main(arguments: list[str] | None = None) -> int:
    """Run requested suites, print a summary, and combine their exit statuses."""
    selected, pytest_arguments = parse_arguments(sys.argv[1:] if arguments is None else arguments)
    if selected.list:
        print("Available suites: python (pytest), rust (cargo test --workspace)")
        return 0
    names = [name for name in SUITES if not (selected.python or selected.rust) or getattr(selected, name)]
    results: dict[str, int] = {}
    for name in names:
        results[name] = run_suite(name, serial=selected.serial, pytest_arguments=pytest_arguments)
        if results[name] and selected.fail_fast:
            break
    print("\n=== TEST SUMMARY ===", flush=True)
    for name, status in results.items():
        print(f"{name}: {'PASS' if status == 0 else f'FAIL (exit {status})'}", flush=True)
    return 1 if any(results.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
