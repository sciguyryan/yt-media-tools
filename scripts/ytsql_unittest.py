#!/usr/bin/env python3
"""Run portable normative YT-SQL unittest cases, optionally in parallel shards."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
TESTS = PROJECT / "python" / "yt_discover_tests"
MODULE = "test_normative_ysql_unittest.py"


def _run_shard(index: int, count: int, selector: str | None) -> tuple[int, int, str]:
    env = dict(os.environ, YTSQL_SHARD_INDEX=str(index), YTSQL_SHARD_COUNT=str(count))
    if selector:
        env["YTSQL_CASE_ID"] = selector
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(TESTS), "-p", MODULE]
    result = subprocess.run(command, cwd=PROJECT, env=env, capture_output=True, text=True, check=False)
    return index, result.returncode, result.stdout + result.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=1, help="Independent processes (default: 1)")
    parser.add_argument("--case", help="Select a case ID or unittest method substring")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    selector = args.case
    # Subprocesses isolate adapter state and can be scheduled on different cores.
    # Each shard validates the corpus once, rather than once per case.
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(lambda i: _run_shard(i, args.workers, selector), range(args.workers)))
    for index, status, output in results:
        print(f"=== YT-SQL shard {index + 1}/{args.workers}: {'PASS' if status == 0 else 'FAIL'} ===")
        print(output, end="" if output.endswith("\n") else "\n")
    return int(any(status != 0 for _, status, _ in results))


if __name__ == "__main__":
    raise SystemExit(main())
