"""Validate portable per-case execution configurations without running an engine."""

from __future__ import annotations

import re
from datetime import datetime


class ExecutionConfigError(ValueError):
    """An execution configuration violates the portable contract."""


def validate_execution(value: object) -> None:
    """Require explicit, uniquely named configurations with portable settings."""
    if not isinstance(value, dict) or set(value) != {"configurations"}:
        raise ExecutionConfigError("execution requires configurations only")
    configs = value["configurations"]
    if not isinstance(configs, list) or not configs:
        raise ExecutionConfigError("execution configurations must be a non-empty array")
    seen: set[str] = set()
    for config in configs:
        if not isinstance(config, dict) or set(config) != {"id", "settings"}:
            raise ExecutionConfigError("each configuration requires id and settings only")
        name = config["id"]
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_-]*", name) is None or name in seen:
            raise ExecutionConfigError("invalid or duplicate execution configuration ID")
        seen.add(name)
        settings = config["settings"]
        if not isinstance(settings, dict) or set(settings) - {"optimisation", "clock"}:
            raise ExecutionConfigError("unknown portable execution setting")
        if "optimisation" in settings and settings["optimisation"] not in ("enabled", "disabled"):
            raise ExecutionConfigError("optimisation must be enabled or disabled")

        if "clock" in settings:
            clock = settings["clock"]
            if (
                not isinstance(clock, str)
                or re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})",
                    clock,
                )
                is None
            ):
                raise ExecutionConfigError("clock must be an offset-aware RFC 3339 timestamp")
            try:
                parsed = datetime.fromisoformat(clock.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ExecutionConfigError("clock must be a valid timestamp") from exc
            if parsed.utcoffset() is None:
                raise ExecutionConfigError("clock must have an explicit UTC offset")
