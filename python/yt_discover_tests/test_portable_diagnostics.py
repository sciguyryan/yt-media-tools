"""Portable diagnostic classification and matching contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("portable_diagnostics", ROOT / "yt-sql/diagnostics.py")
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


@pytest.mark.parametrize("category", sorted(module.CATEGORIES))
def test_supported_categories(category: str) -> None:
    assert module.validate_diagnostic({"category": category}) == {"category": category}


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"category": "crash"},
        {"category": "syntax", "code": ""},
        {"category": "syntax", "message": "anything"},
        {"category": 1},
        {"category": "type", "code": 3},
    ],
)
def test_reject_unclassified_or_malformed_diagnostics(value: object) -> None:
    with pytest.raises(module.DiagnosticError):
        module.validate_diagnostic(value)


def test_category_and_optional_code_matching() -> None:
    assert module.diagnostics_match({"category": "syntax"}, {"category": "syntax", "code": "P001"})
    assert module.diagnostics_match({"category": "syntax", "code": "P001"}, {"category": "syntax", "code": "P001"})
    assert not module.diagnostics_match({"category": "syntax"}, {"category": "resolution"})
    assert not module.diagnostics_match({"category": "syntax", "code": "P001"}, {"category": "syntax", "code": "P002"})
    assert not module.diagnostics_match({"category": "syntax", "code": "P001"}, {"category": "syntax"})
