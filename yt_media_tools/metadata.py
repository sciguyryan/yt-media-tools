"""Normalisation helpers for yt-dlp metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


SCALAR_TYPES = (str, int, float, bool, type(None))


def normalise_record(info: dict[str, Any]) -> dict[str, Any]:
    """Keep all top-level scalar metadata and retain the original JSON for raw paths."""
    record = {key: value for key, value in info.items() if isinstance(key, str) and isinstance(value, SCALAR_TYPES)}
    record["_raw"] = deepcopy(info)
    return record


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return metadata suitable for JSONL output without private implementation keys."""
    return {key: value for key, value in record.items() if not key.startswith("_")}
