"""Compare portable observable query outcomes without engine-specific exceptions."""

from __future__ import annotations

from diagnostics import DiagnosticError, diagnostics_match, validate_diagnostic
from typed_values import TypedValueError, compare_rows, validate_values


class OutcomeError(ValueError):
    """An observed outcome violates the portable comparison contract."""


def _validate(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise OutcomeError("outcome must be a version 1 object")
    kind = value.get("outcome")
    if kind == "rows":
        if set(value) != {"version", "outcome", "columns", "rows"}:
            raise OutcomeError("rows outcome has missing or unexpected fields")
        columns = value["columns"]
        if not isinstance(columns, list) or any(
            not isinstance(c, str) or any(0xD800 <= ord(char) <= 0xDFFF for char in c) for c in columns
        ):
            raise OutcomeError("columns must be an array of strings")
        try:
            validate_values(value["rows"], len(columns))
        except TypedValueError as exc:
            raise OutcomeError(str(exc)) from exc
    elif kind == "error":
        if set(value) != {"version", "outcome", "error"}:
            raise OutcomeError("error outcome has missing or unexpected fields")
        try:
            validate_diagnostic(value["error"])
        except DiagnosticError as exc:
            raise OutcomeError(str(exc)) from exc
    else:
        raise OutcomeError("unknown observable outcome")
    return value


def outcomes_match(expected: object, observed: object, *, order: str) -> bool:
    """Compare two validated outcomes; unexpected failures are not outcomes.

    The observed error must already have been classified as a language diagnostic
    by an implementation adapter. Never convert arbitrary exceptions to errors.
    """
    if order not in ("ordered", "unordered"):
        raise OutcomeError("order must be ordered or unordered")
    left, right = _validate(expected), _validate(observed)
    if left["outcome"] != right["outcome"]:
        return False
    if left["outcome"] == "error":
        return diagnostics_match(left["error"], right["error"])
    return left["columns"] == right["columns"] and compare_rows(left["rows"], right["rows"], ordered=order == "ordered")
