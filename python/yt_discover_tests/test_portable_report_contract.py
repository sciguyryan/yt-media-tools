"""Versioned CI report validation is independent of the executing adapter."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from validate_report import ReportError, load_report, validate_report  # noqa: E402
from run_conformance import run  # noqa: E402


def test_generated_report_satisfies_contract() -> None:
    validate_report(run())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(version=True),
        lambda r: r["counts"].update(pass_=1),
        lambda r: r["counts"].update(pass_=0),
        lambda r: r["results"].append(dict(r["results"][0])),
        lambda r: r["results"][0].update(status="unknown"),
        lambda r: r["results"][0].update(detail=None),
        lambda r: r.update(unknown="extra"),
    ],
)
def test_invalid_report_is_rejected(mutation) -> None:
    report = run()
    mutation(report)
    with pytest.raises(ReportError):
        validate_report(report)


def test_duplicate_json_key_is_rejected(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text('{"version":1,"version":1}', encoding="utf-8")
    with pytest.raises(ReportError, match="duplicate JSON key"):
        load_report(report)


def test_saved_report_can_be_validated(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text(json.dumps(run()), encoding="utf-8")
    assert load_report(path)["counts"]["pass"] == 1
