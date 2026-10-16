#!/usr/bin/env python3
"""Exercise the supported native inspection CLI without enabling downloads."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path, help="Path to built yt-download-rs executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    executable = args.executable.resolve()
    fixture = (root / "rust/crates/yt-downloader/fixtures/python-machine-contract.json").read_bytes()
    cases = [
        (["--schema-json"], 0, fixture, b""),
        (
            ["--schema-json", "--profile", "music"],
            1,
            b"",
            b"yt-download-rs: --schema-json cannot be combined with other options\n",
        ),
        (["--capabilities"], 1, b"", b"yt-download-rs: --capabilities is not yet implemented; use yt-download.py\n"),
        (
            ["--capabilities-json"],
            1,
            b"",
            b"yt-download-rs: --capabilities-json is not yet implemented; use yt-download.py\n",
        ),
        (
            ["--capabilities", "--capabilities-json"],
            1,
            b"",
            b"yt-download-rs: --capabilities cannot be combined with other options\n",
        ),
        (
            ["--profile", "music", "--schema-json"],
            1,
            b"",
            b"yt-download-rs: --schema-json cannot be combined with other options\n",
        ),
        (["--profile", "--list-profiles"], 1, b"", b"yt-download-rs: missing value for --profile\n"),
        (["--audio-format"], 1, b"", b"yt-download-rs: missing value for --audio-format\n"),
        (
            ["--playlist", "--no-playlist"],
            1,
            b"",
            b"yt-download-rs: conflicting options --playlist and --no-playlist\n",
        ),
        (
            ["--no-playlist", "--playlist"],
            1,
            b"",
            b"yt-download-rs: conflicting options --playlist and --no-playlist\\n",
        ),
        (
            ["--audio-only", "--no-audio-only"],
            1,
            b"",
            b"yt-download-rs: conflicting options --audio-only and --no-audio-only\\n",
        ),
        (
            ["--embed-metadata", "--no-embed-metadata"],
            1,
            b"",
            b"yt-download-rs: conflicting options --embed-metadata and --no-embed-metadata\\n",
        ),
        (
            ["--embed-chapters", "--no-embed-chapters"],
            1,
            b"",
            b"yt-download-rs: conflicting options --embed-chapters and --no-embed-chapters\\n",
        ),
        (
            ["--embed-thumbnail", "--no-embed-thumbnail"],
            1,
            b"",
            b"yt-download-rs: conflicting options --embed-thumbnail and --no-embed-thumbnail\\n",
        ),
        (["--audio-quality"], 1, b"", b"yt-download-rs: missing value for --audio-quality\\n"),
        (["--defaults"], 1, b"", b"yt-download-rs: missing value for --defaults\\n"),
        (["--profile"], 1, b"", b"yt-download-rs: missing value for --profile\\n"),
    ]
    failures = 0
    for argv, status, stdout, stderr in cases:
        result = subprocess.run([str(executable), *argv], cwd=root, capture_output=True, check=False)
        passed = (result.returncode, result.stdout, result.stderr) == (status, stdout, stderr)
        print(f"{'PASS' if passed else 'FAIL'}: {' '.join(argv)}")
        if not passed:
            failures += 1
            print(f"  expected exit={status}, stdout={stdout[:120]!r}, stderr={stderr!r}")
            print(f"  actual   exit={result.returncode}, stdout={result.stdout[:120]!r}, stderr={result.stderr!r}")
    print(f"{len(cases) - failures}/{len(cases)} CLI contract checks passed")
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
