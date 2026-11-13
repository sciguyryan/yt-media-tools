#!/usr/bin/env python3
"""Run the routine pytest suite using the project's supported test policy."""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    """Run pytest with the routine parallel policy and pass through arguments."""
    arguments = list(sys.argv[1:])
    serial = False
    if "--serial" in arguments:
        arguments.remove("--serial")
        serial = True

    command = [sys.executable, "-m", "pytest"]
    if not serial:
        # Worker count follows the machine and work-stealing re-balances the
        # suite when the subprocess-heavy conformance harness tests saturate a
        # worker; fixed small pools left the tail of the run single-threaded.
        command.extend(("-n", "auto", "--dist", "worksteal"))
    command.extend(arguments)
    return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main())
