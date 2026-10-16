"""Deterministic, side-effect-free comparison harness for the two entry points.

This is deliberately a foundation, not a claim of feature parity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys


def capture(command: list[str], cwd: Path) -> dict[str, object]:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=20)
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rust-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Write deterministic comparison evidence as JSON")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    binary = args.rust_binary.resolve()
    if not binary.is_file():
        parser.error(f"Rust binary not found: {binary}")
    # Schema parity is a genuine cross-language contract: verify that the
    # embedded reference remains identical to Python's current output.
    fixture = root / "rust/crates/yt-downloader/fixtures/python-machine-contract.json"
    schema = subprocess.run(
        [sys.executable, str(root / "yt-download.py"), "--schema-json"],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=20,
    )
    if schema.returncode != 0:
        print("Python schema inspection failed:", file=sys.stderr)
        sys.stderr.buffer.write(schema.stderr)
        return 2
    if schema.stdout != fixture.read_bytes():
        print("Rust schema fixture differs from Python --schema-json output.", file=sys.stderr)
        return 1

    cases = ("--version", "--help")
    report = {
        "status": "scaffold-only; output parity not expected",
        "cases": {
            flag: {
                "python": capture([sys.executable, str(root / "yt-download.py"), flag], root),
                "rust": capture([str(binary), flag], root),
            }
            for flag in cases
        },
    }
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
