"""Dynamic query schema built from normalised yt-dlp metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


SCALAR_TYPES = (str, int, float, bool, type(None))

KNOWN_FIELD_TYPES = {
    "id": "string",
    "title": "string",
    "upload_date": "date",
    "duration": "duration",
    "view_count": "count",
    "like_count": "count",
    "comment_count": "count",
    "channel_follower_count": "count",
    "playlist_index": "count",
    "source_index": "count",
    "uploader": "string",
    "uploader_id": "string",
    "channel": "string",
    "channel_id": "string",
    "live_status": "string",
    "availability": "string",
    "is_live": "boolean",
    "was_live": "boolean",
    "webpage_url": "string",
    "playlist_id": "string",
    "playlist_title": "string",
    "timestamp": "datetime",
    "release_timestamp": "datetime",
    "modified_timestamp": "datetime",
}

ALIASES = {
    "views": "view_count",
    "likes": "like_count",
    "comments": "comment_count",
    "date": "upload_date",
    "url": "webpage_url",
}


@dataclass(frozen=True)
class FieldInfo:
    """Description of a field visible to the query language."""

    name: str
    kind: str
    nullable: bool
    alias_of: str | None = None
    dynamic: bool = False


class QuerySchema:
    """Resolve known, aliased, dynamic, and raw nested metadata fields."""

    def __init__(self, records: Iterable[dict[str, Any]]) -> None:
        self.records = tuple(records)
        self._fields: dict[str, FieldInfo] = {}
        self._build()

    def _build(self) -> None:
        for name, kind in KNOWN_FIELD_TYPES.items():
            nullable = any(record.get(name) is None for record in self.records) or not self.records
            self._fields[name.casefold()] = FieldInfo(name, kind, nullable, dynamic=False)

        observed: dict[str, list[Any]] = {}
        for record in self.records:
            for name, value in record.items():
                if name.startswith("_"):
                    continue
                if isinstance(value, SCALAR_TYPES):
                    observed.setdefault(name, []).append(value)

        for name, values in observed.items():
            key = name.casefold()
            canonical = self._fields.get(key)
            if canonical is not None:
                continue
            kind = infer_kind(name, values)
            nullable = any(value is None for value in values) or len(values) < len(self.records)
            self._fields[key] = FieldInfo(name, kind, nullable, dynamic=True)

        for alias, target in ALIASES.items():
            target_info = self._fields.get(target.casefold())
            if target_info is not None:
                self._fields[alias.casefold()] = FieldInfo(
                    alias,
                    target_info.kind,
                    target_info.nullable,
                    alias_of=target_info.name,
                    dynamic=False,
                )

    def resolve(self, name: str) -> FieldInfo | None:
        """Resolve a field name, including raw dotted paths."""
        lowered = name.casefold()
        if lowered.startswith("raw."):
            path = name[4:]
            if not path:
                return None
            values: list[Any] = []
            present = 0
            structured = False
            for record in self.records:
                found, value = raw_path_value(record, path)
                if not found:
                    continue
                present += 1
                if isinstance(value, (dict, list, tuple, set)):
                    structured = True
                values.append(value)
            if present == 0:
                return None
            kind = "structured" if structured else infer_kind(path.split(".")[-1], values)
            return FieldInfo(name, kind, present < len(self.records) or any(v is None for v in values), dynamic=True)
        return self._fields.get(lowered)

    def canonical_name(self, name: str) -> str | None:
        info = self.resolve(name)
        if info is None:
            return None
        return info.alias_of or info.name

    def available_fields(self) -> list[FieldInfo]:
        """Return non-raw fields in deterministic display order."""
        unique: dict[tuple[str, str | None], FieldInfo] = {}
        for info in self._fields.values():
            unique[(info.name.casefold(), info.alias_of)] = info
        return sorted(unique.values(), key=lambda item: (item.alias_of is not None, item.name.casefold()))

    def select_star_fields(self) -> list[FieldInfo]:
        """Return the deterministic scalar field set expanded by ``SELECT *``.

        Canonical built-in fields retain ``KNOWN_FIELD_TYPES`` declaration order.
        Observed top-level dynamic scalar fields follow in case-insensitive lexical
        order. Aliases and ``raw.*`` paths are excluded so star expansion does not
        duplicate values or unexpectedly expose the entire extractor metadata tree.
        """
        builtins = [self._fields[name.casefold()] for name in KNOWN_FIELD_TYPES]
        builtin_keys = {info.name.casefold() for info in builtins}
        dynamic = sorted(
            (
                info
                for info in self._fields.values()
                if info.dynamic and info.alias_of is None and info.name.casefold() not in builtin_keys
            ),
            key=lambda item: item.name.casefold(),
        )
        return builtins + dynamic

    def raw_scalar_paths(self, max_depth: int = 6) -> list[FieldInfo]:
        """Catalogue scalar raw JSON paths without descending through arrays."""
        paths: dict[str, list[Any]] = {}
        presence: dict[str, int] = {}
        for record in self.records:
            raw = record.get("_raw")
            if not isinstance(raw, dict):
                continue
            seen_for_record: set[str] = set()
            for path, value in walk_scalar_paths(raw, max_depth=max_depth):
                paths.setdefault(path, []).append(value)
                if path not in seen_for_record:
                    presence[path] = presence.get(path, 0) + 1
                    seen_for_record.add(path)
        result = []
        for path, values in paths.items():
            result.append(
                FieldInfo(
                    f"raw.{path}",
                    infer_kind(path.split(".")[-1], values),
                    presence.get(path, 0) < len(self.records) or any(v is None for v in values),
                    dynamic=True,
                )
            )
        return sorted(result, key=lambda item: item.name.casefold())


def infer_kind(name: str, values: Iterable[Any]) -> str:
    """Infer a conservative query type from a metadata field and its values."""
    lowered = name.casefold()
    if lowered in KNOWN_FIELD_TYPES:
        return KNOWN_FIELD_TYPES[lowered]
    if lowered.endswith("_timestamp") or lowered == "timestamp":
        return "datetime"
    if lowered.endswith("_date"):
        return "date"
    if lowered.endswith(("_count", "_index")):
        return "count"

    concrete = [value for value in values if value is not None]
    if not concrete:
        return "unknown"
    kinds = set()
    for value in concrete:
        if isinstance(value, bool):
            kinds.add("boolean")
        elif isinstance(value, int):
            kinds.add("integer")
        elif isinstance(value, float):
            kinds.add("number")
        elif isinstance(value, str):
            kinds.add("string")
        else:
            kinds.add("structured")
    if kinds <= {"integer", "number"}:
        return "number" if "number" in kinds else "integer"
    if len(kinds) == 1:
        return next(iter(kinds))
    return "mixed"


def raw_path_value(record: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = record.get("_raw")
    if not isinstance(current, dict):
        return False, None
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def walk_scalar_paths(value: dict[str, Any], *, max_depth: int, prefix: str = ""):
    if max_depth < 1:
        return
    for key, child in value.items():
        if not isinstance(key, str):
            continue
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(child, dict):
            yield from walk_scalar_paths(child, max_depth=max_depth - 1, prefix=path)
        elif isinstance(child, (list, tuple, set)):
            continue
        elif isinstance(child, SCALAR_TYPES):
            yield path, child
