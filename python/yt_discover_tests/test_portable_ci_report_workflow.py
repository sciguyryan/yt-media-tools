"""Keep the CI report gate wired to the independent report validator."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ytsql-conformance.yml"


def test_ci_validates_saved_report_after_conformance_execution() -> None:
    content = WORKFLOW.read_text(encoding="utf-8")
    execute = content.index(
        "python yt-sql/run_conformance.py --implementation python --report-file conformance-python.json"
    )
    validate = content.index("python yt-sql/validate_report.py conformance-python.json")
    upload = content.index("uses: actions/upload-artifact@v4")
    assert execute < validate < upload
    assert "if: always()" in content[execute:validate]
    assert "if [ -f conformance-python.json ]; then" in content[execute:validate]
    assert "if-no-files-found: ignore" in content[upload:]
