#!/usr/bin/env python3
"""Check the committed Rust machine-contract fixture against Python Downloader."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repository = Path(__file__).resolve().parents[2]
    fixture = repository / "rust/crates/yt-downloader/fixtures/python-machine-contract.json"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python interpreter for yt-download.py")
    args = parser.parse_args()

    result = subprocess.run(
        [args.python, str(repository / "yt-download.py"), "--schema-json"],
        cwd=repository,
        capture_output=True,
        check=False,
    )

    if result.returncode:
        sys.stderr.buffer.write(result.stderr)
        print(f"Python schema inspection failed (exit {result.returncode}).", file=sys.stderr)
        return 2

    expected = fixture.read_bytes()

    if result.stdout != expected:
        print("Rust schema fixture differs from the current Python --schema-json output.", file=sys.stderr)
        print("Review the Python contract change before regenerating the fixture.", file=sys.stderr)
        return 1

    print("Rust schema fixture matches Python --schema-json byte for byte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
