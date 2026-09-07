from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from yt_media_tools.dates import DateContext, parse_date_literal, parse_temporal_expression
from yt_media_tools.query import QuerySyntaxError, _parse_duration_text
from yt_media_tools.units import ResolvedUnit, UnitRegistry, load_default_unit_registry


def _write_units(path: Path, units: dict[str, object]) -> Path:
    path.write_text(json.dumps({"format": 1, "language": "test", "units": units}), encoding="utf-8")
    return path


def test_default_registry_resolves_english_and_welsh_units() -> None:
    registry = load_default_unit_registry()
    assert registry.resolve("day") == ResolvedUnit("fixed", 86400.0)
    assert registry.resolve("d") == ResolvedUnit("fixed", 86400.0)
    assert registry.resolve("dydd") == ResolvedUnit("fixed", 86400.0)
    assert registry.resolve("dyddiau") == ResolvedUnit("fixed", 86400.0)
    assert registry.resolve("wythnos") == ResolvedUnit("fixed", 604800.0)
    assert registry.resolve("blwyddyn") == ResolvedUnit("calendar", 12.0)


def test_temporal_expression_accepts_welsh_units_and_shared_short_form() -> None:
    context = DateContext(now=datetime(2026, 9, 7, 12, 0, 0))
    assert parse_temporal_expression("TODAY()-8dyddiau", context, expected="date").isoformat() == "2026-08-30"
    assert parse_temporal_expression("TODAY()-9dydd", context, expected="date").isoformat() == "2026-08-29"
    assert parse_temporal_expression("TODAY()-3d", context, expected="date").isoformat() == "2026-09-04"
    assert parse_temporal_expression("TODAY()-1wythnos", context, expected="date").isoformat() == "2026-08-31"


def test_relative_date_uses_data_driven_units() -> None:
    context = DateContext(now=datetime(2026, 9, 7, 12, 0, 0))
    assert parse_date_literal("2 wythnos ago", context).isoformat() == "2026-08-24"


def test_duration_accepts_fixed_units_from_registry() -> None:
    assert _parse_duration_text("2awr30munud", "2awr30munud", 0) == 9000


def test_duration_rejects_calendar_units() -> None:
    with pytest.raises(QuerySyntaxError, match="cannot be used for a duration"):
        _parse_duration_text("1mis", "1mis", 0)


def test_registry_resolves_derived_units_recursively(tmp_path: Path) -> None:
    path = _write_units(
        tmp_path / "derived.json",
        {
            "tick": {"fixed_seconds": 2},
            "bundle": {"value": 5, "unit": "tick"},
            "crate": {"aliases": ["c"], "value": 3, "unit": "bundle"},
        },
    )
    registry = UnitRegistry.from_files([path])
    assert registry.resolve("crate") == ResolvedUnit("fixed", 30.0)
    assert registry.resolve("c") == ResolvedUnit("fixed", 30.0)


def test_registry_rejects_reused_aliases_across_files(tmp_path: Path) -> None:
    first = _write_units(tmp_path / "first.json", {"day": {"aliases": ["d"], "fixed_seconds": 86400}})
    second = _write_units(tmp_path / "second.json", {"diwrnod": {"aliases": ["d"], "fixed_seconds": 86400}})
    with pytest.raises(ValueError, match="Unit token 'd' is reused"):
        UnitRegistry.from_files([first, second])


def test_registry_rejects_alias_reuse_as_another_canonical_name(tmp_path: Path) -> None:
    path = _write_units(
        tmp_path / "conflict.json",
        {
            "day": {"aliases": ["dydd"], "fixed_seconds": 86400},
            "dydd": {"fixed_seconds": 86400},
        },
    )
    with pytest.raises(ValueError, match="Unit token 'dydd' is reused"):
        UnitRegistry.from_files([path])


def test_registry_rejects_unresolved_derived_unit(tmp_path: Path) -> None:
    path = _write_units(tmp_path / "broken.json", {"week": {"value": 7, "unit": "missing-day"}})
    with pytest.raises(ValueError, match="Unknown unit 'missing-day'"):
        UnitRegistry.from_files([path])


def test_registry_rejects_cycles(tmp_path: Path) -> None:
    path = _write_units(
        tmp_path / "cycle.json",
        {
            "alpha": {"value": 2, "unit": "beta"},
            "beta": {"value": 3, "unit": "alpha"},
        },
    )
    with pytest.raises(ValueError, match="Cyclic unit definition detected"):
        UnitRegistry.from_files([path])
