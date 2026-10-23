"""Validate and check reproducibility of every committed portable fixture family."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent

# Keep the manifest explicit: new fixture families must be deliberately registered.
CHECKS = (
    ("record datasets", "validate_portable_dataset.py", None),
    ("source topology", "validate_portable_topology.py", None),
    ("facet topology", "validate_portable_facets.py", None),
    ("record reproducibility", "export_portable_dataset.py", "--check"),
    ("source reproducibility", "export_portable_topology.py", "--check"),
    ("facet reproducibility", "export_portable_facets.py", "--check"),
    ("Unicode inventory", "build_unicode_fixture_audit.py", "--check"),
    ("cross-fixture relationships", "check_fixture_relationships.py", None),
)


def run_checks() -> list[str]:
    failures = []
    for label, script, option in CHECKS:
        command = [sys.executable, str(HERE / script)]
        if option:
            command.append(option)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        if result.returncode:
            failures.append(f"{label}: {result.stdout.strip()} {result.stderr.strip()}".strip())
        else:
            print(f"PASS {label}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    failures = run_checks()
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
