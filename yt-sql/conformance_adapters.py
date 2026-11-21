"""Explicit execution-adapter registry for the portable conformance harness.

Adapters produce observations only. They never determine approved expectations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

Observation = dict[str, object]
Adapter = Callable[[Path, str, Path], Observation]


def _python(case: Path, configuration: str, root: Path) -> Observation:
    # Import at invocation time to preserve the independent corpus validation
    # boundary and allow the Python adapter to be tested in isolation.
    from run_python_candidate import observe

    return observe(case, configuration=configuration, root=root)


def _rust_binary(root: Path) -> Path:
    import os

    override = os.environ.get("YT_SQL_CONFORMANCE_BIN")
    if override:
        return Path(override)
    return root.parent / "rust" / "target" / "debug" / "yt-sql-conformance"


def _rust(case: Path, configuration: str, root: Path) -> Observation:
    # The Rust adapter is an independent implementation: it communicates over
    # the same observation contract through a subprocess, so adapter crashes
    # remain adapter crashes and never become expected diagnostics.
    import json
    import subprocess

    binary = _rust_binary(root)
    if not binary.exists():
        raise RuntimeError(f"Rust conformance binary is missing: {binary}. Build it with cargo.")
    result = subprocess.run(
        [str(binary), "observe", str(case), configuration, str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Rust adapter failed: {result.stderr.strip() or result.stdout.strip()}")
    try:
        return json.loads(result.stdout)
    except ValueError as exc:
        raise RuntimeError(f"Rust adapter emitted invalid JSON: {result.stdout[:200]}") from exc


ADAPTERS: dict[str, Adapter] = {"python": _python, "rust": _rust}


def resolve(implementation: str) -> Adapter:
    """Return an explicitly registered adapter or reject the implementation."""
    try:
        return ADAPTERS[implementation]
    except KeyError as exc:
        raise ValueError(f"no execution adapter registered for {implementation!r}") from exc
