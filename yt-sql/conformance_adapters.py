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


ADAPTERS: dict[str, Adapter] = {"python": _python}


def resolve(implementation: str) -> Adapter:
    """Return an explicitly registered adapter or reject the implementation."""
    try:
        return ADAPTERS[implementation]
    except KeyError as exc:
        raise ValueError(f"no execution adapter registered for {implementation!r}") from exc
