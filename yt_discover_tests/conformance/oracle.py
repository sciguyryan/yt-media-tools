"""Independent LINQ-style semantic oracle for yt-sql conformance tests.

This module must remain independent from yt-discover query parsing, planning, evaluation
and output code. Test authors write an oracle pipeline separately from the yt-sql text.
The oracle describes intended collection semantics rather than translating query syntax.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterable, TypeVar

T = TypeVar("T")
U = TypeVar("U")
Key = Callable[[Any], Any]


def field(record: dict[str, Any], name: str) -> Any:
    """Read a scalar field, including raw.* paths, without production helpers."""
    if name.startswith("raw."):
        current: Any = record
        for part in name[4:].split("."):
            if not isinstance(current, dict):
                return None
            current = current.get(part)
        return current
    return record.get(name)


def _sort_component(value: Any, descending: bool) -> tuple[bool, Any]:
    # The current yt-sql contract places NULL last for both directions. Descending is
    # handled by stable reverse sorting outside this key, so NULL placement is repaired
    # in a separate stable pass.
    return value is None, value


@dataclass(frozen=True)
class _Ordering:
    key: Key
    descending: bool


class OracleQuery(Generic[T]):
    """Simple, deliberately unoptimised chainable collection query."""

    def __init__(self, rows: Iterable[T]):
        self._rows = list(rows)
        self._orderings: list[_Ordering] = []

    def where(self, predicate: Callable[[T], bool]) -> "OracleQuery[T]":
        self._rows = [row for row in self._rows if predicate(row)]
        self._orderings.clear()
        return self

    def select(self, projector: Callable[[T], U]) -> "OracleQuery[U]":
        self._materialise_ordering()
        return OracleQuery(projector(row) for row in self._rows)

    def distinct(self, key: Callable[[T], Any] | None = None) -> "OracleQuery[T]":
        self._materialise_ordering()
        selector = key or (lambda row: row)
        seen: set[Any] = set()
        unique: list[T] = []
        for row in self._rows:
            marker = _hashable(selector(row))
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(row)
        self._rows = unique
        return self

    def order_by(self, key: Key, *, descending: bool = False) -> "OracleQuery[T]":
        self._orderings = [_Ordering(key, descending)]
        return self

    def then_by(self, key: Key, *, descending: bool = False) -> "OracleQuery[T]":
        if not self._orderings:
            raise ValueError("then_by requires a preceding order_by")
        self._orderings.append(_Ordering(key, descending))
        return self

    def skip(self, count: int) -> "OracleQuery[T]":
        self._materialise_ordering()
        self._rows = self._rows[count:]
        return self

    def take(self, count: int) -> "OracleQuery[T]":
        self._materialise_ordering()
        self._rows = self._rows[:count]
        return self

    def to_list(self) -> list[T]:
        self._materialise_ordering()
        return list(self._rows)

    def _materialise_ordering(self) -> None:
        if not self._orderings:
            return
        # Stable sorts from the least-significant key to the most-significant key model
        # SQL's comma-separated ORDER BY without coupling this oracle to production code.
        for ordering in reversed(self._orderings):
            non_null = [row for row in self._rows if ordering.key(row) is not None]
            null = [row for row in self._rows if ordering.key(row) is None]
            non_null.sort(key=ordering.key, reverse=ordering.descending)
            self._rows = non_null + null
        self._orderings.clear()


def _hashable(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((key, _hashable(item)) for key, item in value.items())
    if isinstance(value, list):
        return tuple(_hashable(item) for item in value)
    return value


def serialise(rows: list[Any], output_format: str, columns: tuple[str, ...]) -> str:
    """Independently serialise oracle results using yt-sql's documented text contract."""
    if output_format == "lines":
        if len(columns) != 1:
            raise ValueError("lines requires one column")
        values = []
        for row in rows:
            value = row[columns[0]] if isinstance(row, dict) else row
            if value is None:
                values.append("")
            elif isinstance(value, bool):
                values.append("true" if value else "false")
            else:
                values.append(str(value))
        return "".join(value + "\n" for value in values)

    dict_rows = [row if isinstance(row, dict) else {columns[0]: row} for row in rows]
    if output_format == "jsonl":
        return "".join(
            json.dumps({column: row.get(column) for column in columns}, ensure_ascii=False) + "\n" for row in dict_rows
        )
    if output_format in {"csv", "tsv"}:
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(
            stream, fieldnames=list(columns), delimiter="," if output_format == "csv" else "\t", lineterminator="\n"
        )
        writer.writeheader()
        for row in dict_rows:
            writer.writerow({column: row.get(column) for column in columns})
        return stream.getvalue()
    raise ValueError(f"unsupported oracle output format: {output_format}")
