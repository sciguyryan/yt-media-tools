"""Run representative YT-SQL grammar probes against the authoritative parser and SQLFluff."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

from yt_media_tools.query_parser import parse_query  # noqa: E402
from format_safely import ReusableSQLFluff  # noqa: E402


def main() -> int:
    cases = json.loads((HERE / "syntax_matrix.json").read_text(encoding="utf-8"))["cases"]
    try:
        engine = ReusableSQLFluff()
    except (ImportError, RuntimeError, ValueError) as exc:
        print(f"SQLFluff 4.4.0 is unavailable: {exc}", file=sys.stderr)
        return 2
    results = []
    for case in cases:
        query = case["query"]
        try:
            parse_query(query)
        except Exception as exc:
            raise SystemExit(f"Authoritative parser rejected {case['id']}: {exc}") from exc
        try:
            engine.parse(query)
            success = True
            diagnostic = ""
        except ValueError as exc:
            success = False
            diagnostic = str(exc)[-1200:]
        results.append(
            {
                "id": case["id"],
                "sqlfluff_parse": "pass" if success else "gap",
                "diagnostic": diagnostic,
            }
        )
    print(
        json.dumps(
            {
                "schema_version": 1,
                "total": len(results),
                "passed": sum(item["sqlfluff_parse"] == "pass" for item in results),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # This is a gap discovery tool, not a CI gate: report all gaps without masking them.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
