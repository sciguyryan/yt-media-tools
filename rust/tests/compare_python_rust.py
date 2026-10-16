"""Deterministic, side-effect-free comparison harness for the two entry points.

This is deliberately a foundation, not a claim of feature parity.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


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

    # Bounded v3 parity: compare stable validation semantics, not presentation.
    # No media targets, network requests, or external downloader are involved.
    documents = {
        "minimal": {"version": 3, "profiles": {"base": {}}},
        "inheritance": {
            "version": 3,
            "values": {"audio": "mp3"},
            "$defaults": {"playlist": False, "embed-metadata": True},
            "profiles": {
                "base": {"audio-format": "$values.audio"},
                "child": {"parent": "base", "embed-metadata": False},
            },
        },
        "missing-parent": {"version": 3, "profiles": {"child": {"parent": "absent"}}},
        "cycle": {
            "version": 3,
            "profiles": {"first": {"parent": "second"}, "second": {"parent": "first"}},
        },
        "invalid-version": {"version": 99, "profiles": {}},
    }
    with tempfile.TemporaryDirectory(prefix="yt-downloader-v3-parity-") as temporary:
        for label, document in documents.items():
            config = Path(temporary) / f"{label}.json"
            config.write_text(json.dumps(document), encoding="utf-8")
            python_result = capture(
                [sys.executable, str(root / "yt-download.py"), "--validate-config", str(config)], root
            )
            rust_result = capture([str(binary), "--validate-config", str(config)], root)
            if (python_result["exit_code"] == 0) != (rust_result["exit_code"] == 0):
                print(f"FAIL: v3 validation acceptance differs for {label}", file=sys.stderr)
                return 1
            if python_result["exit_code"] == 0:
                try:
                    python_payload = json.loads(str(python_result["stdout"]))
                    rust_payload = json.loads(str(rust_result["stdout"]))
                except json.JSONDecodeError:
                    print(f"FAIL: invalid validation JSON for {label}", file=sys.stderr)
                    return 1
                for key in ("kind", "schema_version", "contract_version", "valid", "profile_count", "profiles"):
                    if python_payload.get(key) != rust_payload.get(key):
                        print(f"FAIL: validation field {key} differs for {label}", file=sys.stderr)
                        return 1
            print(f"PASS: v3 validation {label}")

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
