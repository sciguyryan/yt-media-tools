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
    result = run()
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
    assert run(root=corpus)["counts"]["fail"] == 1


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
    result = run(root=corpus)
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
    assert run(root=corpus)["counts"]["xpass"] == 1
