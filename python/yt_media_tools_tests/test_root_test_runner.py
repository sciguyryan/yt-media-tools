"""Contract tests for the combined repository test runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]


def load_runner():
    spec = importlib.util.spec_from_file_location("root_test_runner", ROOT / "run-tests.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_runs_both_suites_even_when_python_fails(capsys):
    runner = load_runner()
    with patch.object(runner.subprocess, "call", side_effect=[1, 0]) as call:
        assert runner.main([]) == 1
    assert call.call_count == 2
    assert call.call_args_list[0].args[0][:2] == [sys.executable, str(ROOT / "python" / "run-tests.py")]
    assert call.call_args_list[1].args[0] == ["cargo", "test", "--workspace"]
    assert call.call_args_list[1].kwargs["cwd"] == ROOT / "rust"
    assert "python: FAIL" in capsys.readouterr().out


def test_python_selection_preserves_existing_pytest_options():
    runner = load_runner()
    with patch.object(runner.subprocess, "call", return_value=0) as call:
        assert runner.main(["--python", "--serial", "--durations=25"]) == 0
    assert call.call_args.args[0][-2:] == ["--serial", "--durations=25"]
    assert call.call_count == 1


def test_rust_selection_and_missing_cargo(capsys):
    runner = load_runner()
    with patch.object(runner.subprocess, "call", side_effect=FileNotFoundError(2, "missing", "cargo")):
        assert runner.main(["--rust"]) == 1
    assert "cargo" in capsys.readouterr().err


def test_fail_fast_stops_after_first_failure():
    runner = load_runner()
    with patch.object(runner.subprocess, "call", return_value=2) as call:
        assert runner.main(["--fail-fast"]) == 1
    assert call.call_count == 1


def test_list_does_not_execute_suites(capsys):
    runner = load_runner()
    with patch.object(runner.subprocess, "call") as call:
        assert runner.main(["--list"]) == 0
    call.assert_not_called()
    assert "python" in capsys.readouterr().out


def test_pytest_arguments_not_forwarded_to_rust():
    runner = load_runner()
    with patch.object(runner.subprocess, "call") as call:
        try:
            runner.main(["--rust", "--durations=25"])
        except SystemExit as error:
            assert error.code == 2
        else:
            raise AssertionError("Expected invalid suite arguments to be rejected")
    call.assert_not_called()


def test_help_is_available_without_test_dependencies():
    result = subprocess.run(
        [sys.executable, str(ROOT / "run-tests.py"), "--help"], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "--python" in result.stdout and "--rust" in result.stdout
