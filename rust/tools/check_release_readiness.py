#!/usr/bin/env python3
"""Check static prerequisites for a Rust Downloader Part 3 acceptance candidate."""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    manifest = tomllib.loads((root / "rust/crates/yt-downloader/Cargo.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "rust/Cargo.lock").read_text(encoding="utf-8"))
    fixture = json.loads(
        (root / "rust/crates/yt-downloader/fixtures/python-machine-contract.json").read_text(encoding="utf-8")
    )
    failures: list[str] = []

    packages = lock.get("package", [])
    if len(packages) <= 1:
        failures.append("Cargo.lock contains no resolved transitive dependencies; regenerate it using Cargo.")
    if not any(p.get("name") == "home" and p.get("version") == "0.5.12" for p in packages):
        failures.append("Cargo.lock does not resolve home 0.5.12.")
    if manifest.get("dependencies", {}).get("home") != "=0.5.12":
        failures.append("The Rust Downloader manifest does not pin home 0.5.12.")
    if not isinstance(fixture, dict) or not fixture:
        failures.append("The Python machine-contract fixture is not a nonempty JSON object.")

    for failure in failures:
        print(f"FAIL: {failure}", file=sys.stderr)
    if failures:
        return 1
    print("PASS: static Part 3 release prerequisites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
