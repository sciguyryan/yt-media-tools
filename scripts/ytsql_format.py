"""Convenient repository-level entry point for guarded YT-SQL formatting.

Usage: python scripts/ytsql_format.py check [paths...]
       python scripts/ytsql_format.py format [paths...]
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yt-sql/sqlfluff"))

from format_safely import main as format_main  # noqa: E402


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"check", "format"}:
        print("Usage: python scripts/ytsql_format.py {check|format} [paths...]", file=sys.stderr)
        return 2
    action = "--check" if sys.argv[1] == "check" else "--write"
    return format_main([action, *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
