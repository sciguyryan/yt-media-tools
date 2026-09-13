"""Normalisation helpers for yt-dlp metadata."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .schema import KNOWN_COLLECTION_TYPES


SCALAR_TYPES = (str, int, float, bool, type(None))


def _normalise_known_collection(name: str, value: Any) -> Any:
    """Return a backend-neutral collection value for a declared metadata family."""
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        return value
    copied = deepcopy(list(value))
    if name in {"tags", "categories"}:
        # yt-sql defines a deterministic lexical order for these scalar collections.
        # Do not expose whichever order an extractor happened to return.
        return sorted(copied, key=lambda item: (item is None, str(item) if item is not None else ""))
    return copied


def normalise_record(info: dict[str, Any]) -> dict[str, Any]:
    """Normalise query-visible metadata while retaining the original JSON for raw paths."""
    record = {key: value for key, value in info.items() if isinstance(key, str) and isinstance(value, SCALAR_TYPES)}
    for name in KNOWN_COLLECTION_TYPES:
        if name in info:
            record[name] = _normalise_known_collection(name, info[name])
    record["_raw"] = deepcopy(info)
    return record
