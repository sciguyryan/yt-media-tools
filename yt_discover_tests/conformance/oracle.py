"""Independent expected-result helpers for deterministic conformance tests."""

from __future__ import annotations

from collections.abc import Iterable


def project(rows: Iterable[dict[str, object]], fields: tuple[str, ...]) -> list[dict[str, object]]:
    """Project rows without depending on the YT-SQL parser or executor."""

    return [{field: row.get(field) for field in fields} for row in rows]


def filter_equals(
    rows: Iterable[dict[str, object]],
    field: str,
    value: object,
) -> list[dict[str, object]]:
    """Apply ordinary SQL-like equality where NULL never compares equal."""

    return [row for row in rows if row.get(field) is not None and row.get(field) == value]


def order_by(
    rows: Iterable[dict[str, object]],
    field: str,
    *,
    reverse: bool = False,
) -> list[dict[str, object]]:
    """Sort non-NULL values before NULL values."""

    ordered = sorted(rows, key=lambda row: (row.get(field) is None, row.get(field)))
    return list(reversed(ordered)) if reverse else ordered


def distinct(rows: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Preserve the first occurrence of each projected row."""

    seen: set[tuple[tuple[str, object], ...]] = set()
    result: list[dict[str, object]] = []
    for row in rows:
        key = tuple(row.items())
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
