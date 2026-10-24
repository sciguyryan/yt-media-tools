"""Run representative YT-SQL grammar probes against the authoritative parser and SQLFluff."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

from yt_media_tools.query_parser import parse_query  # noqa: E402


def main() -> int:
    cases = json.loads((HERE / "syntax_matrix.json").read_text(encoding="utf-8"))["cases"]
    # Fail before reporting grammar gaps if SQLFluff is unavailable in this interpreter.
    dependency = subprocess.run(
        [sys.executable, "-c", "import sqlfluff; assert sqlfluff.__version__ == '4.4.0'"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if dependency.returncode:
        print(
            "SQLFluff 4.4.0 is unavailable in the current Python interpreter: " + dependency.stderr.strip(),
            file=sys.stderr,
        )
        return 2
    results = []
    for case in cases:
        query = case["query"]
        try:
            parse_query(query)
        except Exception as exc:
            raise SystemExit(f"Authoritative parser rejected {case['id']}: {exc}") from exc
        parsed = subprocess.run(
            [sys.executable, str(HERE / "run.py"), "parse", "--config", str(ROOT / ".sqlfluff-ysql"), "-"],
            cwd=ROOT,
            input=query,
            text=True,
            capture_output=True,
            check=False,
        )
        if "Traceback (most recent call last)" in parsed.stderr or "ModuleNotFoundError" in parsed.stderr:
            print(f"SQLFluff launcher failed for {case['id']}: {parsed.stderr.strip()}", file=sys.stderr)
            return 2
        success = (
            parsed.returncode == 0
            and "unparsable:" not in parsed.stdout.lower()
            and "unlexable:" not in parsed.stdout.lower()
        )
        results.append(
            {
                "id": case["id"],
                "sqlfluff_parse": "pass" if success else "gap",
                "diagnostic": "" if success else (parsed.stderr + parsed.stdout)[-1200:],
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
