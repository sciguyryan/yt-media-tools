"""Validate portable named parameter bindings without executing YT-SQL."""

from __future__ import annotations

import re

from typed_values import TypedValueError, _typed


class ParameterError(ValueError):
    """A named parameter violates the portable binding contract."""


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z", re.ASCII)


def validate_parameters(parameters: object) -> None:
    """Validate named bindings; preserve values and distinguish missing from NULL."""
    if not isinstance(parameters, dict):
        raise ParameterError("parameters must be an object")
    for name, value in parameters.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise ParameterError(f"invalid parameter name: {name!r}")
        try:
            _typed(value)
        except TypedValueError as exc:
            raise ParameterError(f"parameter {name!r}: {exc}") from exc
