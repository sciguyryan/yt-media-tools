"""Behavioural checks for the portable cross-platform certification gate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "compare_platform_reports", ROOT / "yt-sql" / "compare_platform_reports.py"
)
assert SPEC is not None and SPEC.loader is not None
sys.path.insert(0, str(ROOT / "yt-sql"))
parity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(parity)


def report(ids: list[tuple[str, str]]) -> dict[str, object]:
    statuses = ("pass", "fail", "error", "xfail", "xpass")
    return {
        "version": 1,
        "implementation": "python",
        "configuration": "default",
        "results": [{"id": case, "status": status, "detail": ""} for case, status in ids],
        "counts": {status: sum(item[1] == status for item in ids) for status in statuses},
    }


def write(tmp_path: Path, label: str, data: dict[str, object]) -> Path:
    folder = tmp_path / label
    folder.mkdir()
    path = folder / "conformance-python.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_independent_matching_successes_pass(tmp_path: Path) -> None:
    a = write(tmp_path, "linux", report([("a", "pass"), ("b", "pass")]))
    b = write(tmp_path, "windows", report([("a", "pass"), ("b", "pass")]))
    assert parity.compare_reports([a, b])["passed"]


@pytest.mark.parametrize("status", ["fail", "error", "xfail", "xpass"])
def test_matching_nonpasses_do_not_certify_parity(tmp_path: Path, status: str) -> None:
    a = write(tmp_path, "linux", report([("a", status)]))
    b = write(tmp_path, "windows", report([("a", status)]))
    assert not parity.compare_reports([a, b])["passed"]


def test_missing_case_is_rejected(tmp_path: Path) -> None:
    a = write(tmp_path, "linux", report([("a", "pass"), ("b", "pass")]))
    b = write(tmp_path, "macos", report([("a", "pass")]))
    result = parity.compare_reports([a, b])
    assert not result["passed"]
    assert any("case-set mismatch" in problem for problem in result["problems"])


def test_differing_configuration_is_rejected(tmp_path: Path) -> None:
    a = write(tmp_path, "linux", report([("a", "pass")]))
    other = report([("a", "pass")])
    other["configuration"] = "other"
    b = write(tmp_path, "windows", other)
    assert not parity.compare_reports([a, b])["passed"]


def test_duplicate_environment_is_rejected(tmp_path: Path) -> None:
    a = write(tmp_path, "linux", report([("a", "pass")]))
    with pytest.raises(parity.ParityError, match="duplicate environment"):
        parity.compare_reports([a, a])
