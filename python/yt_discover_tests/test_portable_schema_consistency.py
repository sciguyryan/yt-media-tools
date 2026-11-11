"""Behavioural regression for portable nested result values.

This module deliberately does not inspect JSON Schema source files or require
an optional JSON Schema validation library.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_typed_values", ROOT / "yt-sql" / "typed_values.py")
assert SPEC is not None and SPEC.loader is not None
values = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(values)


def test_nested_results_preserve_scalar_distinctions() -> None:
    """A nested array result must not conflate integer, text and NULL values."""
    integer = {"type": "integer", "value": "3"}
    array = {"type": "array", "value": [integer, None]}
    values.validate_values([[array]], 1)
    assert values.compare_rows([[array]], [[array]], ordered=True)
    assert not values.compare_rows([[array]], [[{"type": "array", "value": ["3", None]}]], ordered=True)
