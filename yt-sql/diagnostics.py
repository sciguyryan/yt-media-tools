"""Portable diagnostic categories and comparison, independent of engine exceptions."""

from __future__ import annotations

CATEGORIES = frozenset(
    {
        "syntax",
        "resolution",
        "type",
        "evaluation",
        "unsupported",
        "parameter",
    }
)


class DiagnosticError(ValueError):
    """An expected or observed diagnostic violates the corpus contract."""


def validate_diagnostic(value: object) -> dict[str, str]:
    """Validate an explicitly classified language diagnostic.

    Infrastructure failures, crashes and timeouts are not language diagnostics.
    """
    if not isinstance(value, dict) or set(value) not in ({"category"}, {"category", "code"}):
        raise DiagnosticError("diagnostic must contain category and optional code only")
    category = value["category"]
    if not isinstance(category, str) or category not in CATEGORIES:
        raise DiagnosticError("unknown language diagnostic category")
    if "code" in value and (not isinstance(value["code"], str) or not value["code"].strip()):
        raise DiagnosticError("diagnostic code must be a non-empty string")
    return value


def diagnostics_match(expected: object, observed: object) -> bool:
    """Compare a classified observed language error with an expected error.

    A missing expected code does not constrain the observed code. A specified
    expected code requires an exact match. An unclassified exception must not
    be passed here as an observed language diagnostic.
    """
    left = validate_diagnostic(expected)
    right = validate_diagnostic(observed)
    return left["category"] == right["category"] and ("code" not in left or left["code"] == right.get("code"))
