"""Permanent harness compares approved outcomes, never staged observations."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "yt-sql"))
from run_conformance import HarnessError, run  # noqa: E402


def test_approved_smoke_case_passes() -> None:
    result = run(case_ids=("smoke.source_order_limit",))
    assert result["counts"] == {"pass": 1, "fail": 0, "error": 0, "xfail": 0, "xpass": 0}


def test_unknown_implementation_fails_closed() -> None:
    with pytest.raises(HarnessError, match="no execution adapter"):
        run(implementation="rust")


def test_changed_approved_expectation_is_failure(tmp_path: Path) -> None:
    corpus = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", corpus / "datasets")
    shutil.copytree(ROOT / "yt-sql" / "cases", corpus / "cases")
    shutil.copytree(ROOT / "yt-sql" / "expectations", corpus / "expectations")
    expected = corpus / "cases" / "smoke" / "source_order_limit" / "expected.json"
    payload = json.loads(expected.read_text(encoding="utf-8"))
    payload["rows"] = []
    expected.write_text(json.dumps(payload), encoding="utf-8")
    assert run(root=corpus, case_ids=("smoke.source_order_limit",))["counts"]["fail"] == 1


def test_xfail_never_masks_adapter_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    corpus = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", corpus / "datasets")
    shutil.copytree(ROOT / "yt-sql" / "cases", corpus / "cases")
    shutil.copytree(ROOT / "yt-sql" / "expectations", corpus / "expectations")
    manifest = corpus / "expectations" / "python.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["expectations"]["smoke.source_order_limit"] = {
        "status": "xfail",
        "reason": "Known outcome mismatch",
        "category": "outcome-mismatch",
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    import run_python_candidate

    monkeypatch.setattr(run_python_candidate, "observe", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("crash")))
    result = run(root=corpus, case_ids=("smoke.source_order_limit",))
    assert result["counts"]["error"] == 1
    assert result["counts"]["xfail"] == 0


def test_xpass_is_failure(tmp_path: Path) -> None:
    corpus = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", corpus / "datasets")
    shutil.copytree(ROOT / "yt-sql" / "cases", corpus / "cases")
    shutil.copytree(ROOT / "yt-sql" / "expectations", corpus / "expectations")
    manifest = corpus / "expectations" / "python.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["expectations"]["smoke.source_order_limit"] = {
        "status": "xfail",
        "reason": "Known outcome mismatch",
        "category": "outcome-mismatch",
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert run(root=corpus, case_ids=("smoke.source_order_limit",))["counts"]["xpass"] == 1


def test_registered_adapter_is_invoked_with_explicit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    import conformance_adapters
    import run_python_candidate

    calls = []

    def fake_adapter(case: Path, configuration: str, root: Path):
        calls.append((case, configuration, root))
        return run_python_candidate.observe(case, configuration=configuration, root=root)

    monkeypatch.setitem(conformance_adapters.ADAPTERS, "python", fake_adapter)
    report = run(configuration="default", case_ids=("smoke.source_order_limit",))
    assert report["counts"]["pass"] == 1
    assert len(calls) == 1
    assert calls[0][1:] == ("default", ROOT / "yt-sql")


def test_registered_adapter_crash_is_not_conformance_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    import conformance_adapters

    def crash(case: Path, configuration: str, root: Path):
        raise RuntimeError("adapter unavailable")

    monkeypatch.setitem(conformance_adapters.ADAPTERS, "python", crash)
    report = run(case_ids=("smoke.source_order_limit",))
    assert report["counts"]["error"] == 1
    assert report["results"][0]["detail"] == "RuntimeError: adapter unavailable"


def test_exact_case_selection_preserves_approved_results() -> None:
    result = run(case_ids=("smoke.source_order_limit", "smoke.source_order_limit"))
    assert [item["id"] for item in result["results"]] == ["smoke.source_order_limit"]
    assert result["counts"]["pass"] == 1


def test_unknown_case_selection_fails_closed() -> None:
    with pytest.raises(HarnessError, match="unknown case ID"):
        run(case_ids=("smoke.not_a_case",))


def test_empty_case_selection_fails_closed() -> None:
    with pytest.raises(HarnessError, match="at least one case"):
        run(case_ids=())


def test_case_listing_does_not_execute_adapter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import conformance_adapters
    import run_conformance

    def crash(*args: object) -> dict[str, object]:
        raise AssertionError("adapter should not execute")

    monkeypatch.setitem(conformance_adapters.ADAPTERS, "python", crash)
    monkeypatch.setattr(sys, "argv", ["run_conformance.py", "--list-cases"])
    assert run_conformance.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "smoke.source_order_limit",
        "unicode.lower_dotted_i",
        "unicode.lower_null",
        "unicode.upper_composed_accent",
        "unicode.upper_decomposed_accent",
        "unicode.upper_null",
        "unicode.upper_sharp_s",
    ]


def test_report_file_is_deterministic_and_matches_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import run_conformance

    output = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["run_conformance.py", "--json", "--report-file", str(output)])
    assert run_conformance.main() == 0
    stdout = capsys.readouterr().out
    assert output.read_text(encoding="utf-8") == stdout
    first = output.read_bytes()
    assert run_conformance.main() == 0
    capsys.readouterr()
    assert output.read_bytes() == first


def test_report_file_written_for_conformance_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import run_conformance
    import conformance_adapters

    output = tmp_path / "failure.json"
    monkeypatch.setitem(
        conformance_adapters.ADAPTERS, "python", lambda *args: {"status": "success", "columns": [], "rows": []}
    )
    monkeypatch.setattr(
        sys, "argv", ["run_conformance.py", "--report-file", str(output), "--case", "smoke.source_order_limit"]
    )
    assert run_conformance.main() == 1
    assert json.loads(output.read_text(encoding="utf-8"))["counts"]["error"] == 1


def test_report_file_publication_failure_does_not_leave_temporary_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import run_conformance
    import os

    output = tmp_path / "report.json"
    output.write_text("previous", encoding="utf-8")

    def fail_replace(*args: object) -> None:
        raise OSError("publication refused")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication refused"):
        run_conformance.write_report(output, {"version": 1})
    assert output.read_text(encoding="utf-8") == "previous"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["report.json"]
