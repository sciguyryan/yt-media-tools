"""Timestamp precision and offset boundaries for portable typed values."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_timestamp_values", ROOT / "yt-sql/typed_values.py")
assert SPEC and SPEC.loader
values = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(values)


def _stamp(text: str) -> dict[str, str]:
    return {"type": "timestamp", "value": text}


def test_microsecond_precision_is_preserved() -> None:
    assert values.compare_rows(
        [[_stamp("2026-01-01T00:00:00.123456Z")]], [[_stamp("2026-01-01T01:00:00.123456+01:00")]], ordered=True
    )
    assert not values.compare_rows(
        [[_stamp("2026-01-01T00:00:00.123456Z")]], [[_stamp("2026-01-01T00:00:00.123455Z")]], ordered=True
    )


def test_six_digit_fraction_and_offset_equivalence() -> None:
    assert values.compare_rows(
        [[_stamp("2026-01-01T00:00:00Z")]], [[_stamp("2026-01-01T00:00:00.000000+00:00")]], ordered=True
    )
    assert values.compare_rows(
        [[_stamp("2026-01-01T00:00:00+05:30")]], [[_stamp("2025-12-31T18:30:00Z")]], ordered=True
    )


@pytest.mark.parametrize(
    "text",
    [
        "2026-01-01T00:00:00.1234567Z",
        "2026-01-01T00:00:00.0000001Z",
        "2026-01-01T00:00:00.Z",
        "2026-01-01T00:00:00+24:00",
        "2026-01-01T00:00:00+01:60",
        "2026-01-01T00:00:60Z",
        "2026-02-29T00:00:00Z",
        "2026-01-01T00:00:00",
    ],
)
def test_invalid_or_unrepresentable_timestamps_are_rejected(text: str) -> None:
    with pytest.raises(values.TypedValueError):
        values.validate_values([[_stamp(text)]], 1)
