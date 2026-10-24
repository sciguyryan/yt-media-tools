"""Regression tests for the local pre-staging result cache helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("local_precommit", ROOT / "pre-commit.py")


def _module():
    import sys

    module = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = module
    SPEC.loader.exec_module(module)
    return module


def test_failed_ids_are_sorted_and_only_failed() -> None:
    module = _module()
    assert module.cached_failures({"tests": {"z": "FAIL", "a": "PASS", "b": "FAIL", "c": "SKIPPED"}}) == ["b", "z"]


def test_rust_result_parser_preserves_skips_and_failures() -> None:
    module = _module()
    assert module.rust_outcomes(
        "test suite::ok ... ok\ntest suite::bad ... FAILED\ntest suite::ignored ... ignored\n"
    ) == {"suite::ok": "PASS", "suite::bad": "FAIL", "suite::ignored": "SKIPPED"}


def test_python_command_adds_report_plugin_and_failed_ids() -> None:
    module = _module()
    check = next(item for item in module.checks() if item.name == "python-tests")
    command = module.test_command(check, ["tests/test_a.py::test_one"])
    assert command[-3:] == ("-p", "scripts.precommit_pytest_report", "tests/test_a.py::test_one")
