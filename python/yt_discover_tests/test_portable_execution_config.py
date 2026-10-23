"""Portable execution-configuration contract regression tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_execution_config", ROOT / "yt-sql/execution_config.py")
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_valid_execution_matrix() -> None:
    module.validate_execution(
        {
            "configurations": [
                {"id": "default", "settings": {}},
                {"id": "optimised", "settings": {"optimisation": "enabled"}},
                {"id": "unoptimised", "settings": {"optimisation": "disabled"}},
            ]
        }
    )


@pytest.mark.parametrize(
    "execution",
    [
        {},
        {"configurations": []},
        {"configurations": {}},
        {"configurations": [{"id": "a", "settings": {}}, {"id": "a", "settings": {}}]},
        {"configurations": [{"id": "Bad ID", "settings": {}}]},
        {"configurations": [{"id": "a", "settings": {"optimisation": True}}]},
        {"configurations": [{"id": "a", "settings": {"optimisation": "automatic"}}]},
        {"configurations": [{"id": "a", "settings": {"unknown": "value"}}]},
        {"configurations": [{"id": "a"}]},
        {"configurations": [{"id": "a", "settings": {}, "skip": True}]},
    ],
)
def test_invalid_execution_matrix(execution: object) -> None:
    with pytest.raises(module.ExecutionConfigError):
        module.validate_execution(execution)


def test_explicit_clock_accepts_utc_and_offset() -> None:
    module.validate_execution(
        {
            "configurations": [
                {"id": "utc", "settings": {"clock": "2026-09-01T10:30:00Z"}},
                {"id": "offset", "settings": {"clock": "2026-09-01T12:30:00+02:00"}},
            ]
        }
    )


@pytest.mark.parametrize(
    "clock",
    [
        "2026-09-01T10:30:00",
        "2026-02-30T10:30:00Z",
        "2026-09-01",
        "2026-09-01T10:30:00+25:00",
        None,
        123,
    ],
)
def test_invalid_clock_is_rejected(clock: object) -> None:
    with pytest.raises(module.ExecutionConfigError):
        module.validate_execution(
            {
                "configurations": [
                    {"id": "default", "settings": {"clock": clock}},
                ]
            }
        )
