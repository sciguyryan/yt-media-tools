"""Collect pytest node outcomes for the opt-in local pre-staging gate."""

from __future__ import annotations

import json
import os
from pathlib import Path

_RESULTS: dict[str, str] = {}


def pytest_runtest_logreport(report: object) -> None:
    """Record the final status of each node without relying on console parsing."""
    nodeid = getattr(report, "nodeid", None)
    when = getattr(report, "when", None)
    if not isinstance(nodeid, str):
        return
    if getattr(report, "failed", False):
        _RESULTS[nodeid] = "FAIL"
    elif getattr(report, "skipped", False) and nodeid not in _RESULTS:
        _RESULTS[nodeid] = "SKIPPED"
    elif when == "call" and getattr(report, "passed", False) and nodeid not in _RESULTS:
        _RESULTS[nodeid] = "PASS"


def pytest_sessionfinish(session: object, exitstatus: int) -> None:
    """Write results from the controller only, including partial failed runs."""
    if hasattr(session.config, "workerinput"):
        return
    destination = os.environ.get("YT_PRECOMMIT_PYTEST_REPORT")
    if destination:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_RESULTS, indent=2, sort_keys=True) + "\n", encoding="utf-8")
