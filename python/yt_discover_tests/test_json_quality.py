"""Regression tests for strict repository JSON quality checks."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/json_quality.py"
spec = importlib.util.spec_from_file_location("json_quality", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_json_quality_repository() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=ROOT, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_duplicate_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"x": 1, "x": 2}\n', encoding="utf-8")
    assert "duplicate" in module.check_file(path, write=False, format_check=True)


def test_invalid_unicode_rejected(tmp_path: Path) -> None:
    path = tmp_path / "surrogate.json"
    path.write_text('{"x": "\\ud800"}\n', encoding="utf-8")
    assert "surrogate" in module.check_file(path, write=False, format_check=True)


def test_non_finite_number_rejected(tmp_path: Path) -> None:
    path = tmp_path / "nan.json"
    path.write_text('{"x": NaN}\n', encoding="utf-8")
    assert "non-finite" in module.check_file(path, write=False, format_check=True)


def test_formatting_and_write(tmp_path: Path) -> None:
    path = tmp_path / "format.json"
    path.write_text('{"x":1}\n', encoding="utf-8")
    assert "format differs" in module.check_file(path, write=False, format_check=True)
    assert module.check_file(path, write=True, format_check=True) is None
    assert path.read_text(encoding="utf-8") == json.dumps({"x": 1}, indent=2) + "\n"


def test_deleted_tracked_json_is_skipped(tmp_path: Path, monkeypatch) -> None:
    class GitResult:
        returncode = 0
        stdout = b"present.json\0removed.json\0"

    (tmp_path / "present.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: GitResult())
    assert module.tracked_json() == [tmp_path / "present.json"]
