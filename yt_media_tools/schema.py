"""Dynamic query schema built from normalised yt-dlp metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .query_types import CollectionOrdering, QueryType, StructuredMember, StructuredShape


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


def _structured_member(name: str, kind: str, *, nullable: bool = True) -> StructuredMember:
    """Construct one member of a stable logical metadata record."""
    return StructuredMember(name, QueryType.scalar(kind, nullable=nullable))


FORMAT_RECORD_TYPE = QueryType.structured(
    (
        _structured_member("format_id", "string"),
        _structured_member("ext", "string"),
        _structured_member("width", "count"),
        _structured_member("height", "count"),
        _structured_member("resolution", "string"),
        _structured_member("fps", "number"),
        _structured_member("aspect_ratio", "number"),
        _structured_member("vcodec", "string"),
        _structured_member("acodec", "string"),
        _structured_member("container", "string"),
        _structured_member("protocol", "string"),
        _structured_member("dynamic_range", "string"),
        _structured_member("tbr", "number"),
        _structured_member("vbr", "number"),
        _structured_member("abr", "number"),
        _structured_member("asr", "number"),
        _structured_member("audio_channels", "count"),
        _structured_member("filesize", "count"),
        _structured_member("filesize_approx", "count"),
        _structured_member("language", "string"),
        _structured_member("format_note", "string"),
    ),
    nullable=True,
)

CHAPTER_RECORD_TYPE = QueryType.structured(
    (
        _structured_member("title", "string"),
        _structured_member("start_time", "duration"),
        _structured_member("end_time", "duration"),
    ),
    nullable=True,
)

THUMBNAIL_RECORD_TYPE = QueryType.structured(
    (
        _structured_member("id", "string"),
        _structured_member("url", "string"),
        _structured_member("width", "count"),
        _structured_member("height", "count"),
    ),
    nullable=True,
)


KNOWN_COLLECTION_TYPES = {
    # Scalar collections receive an explicit yt-sql order independent of backend
    # return order. Structured collections remain non-positional until a logical
    # ordering contract is established for their record semantics.
    "tags": QueryType.collection(
        QueryType.scalar("string", nullable=True),
        ordering=CollectionOrdering.STABLE,
    ),
    "categories": QueryType.collection(
        QueryType.scalar("string", nullable=True),
        ordering=CollectionOrdering.STABLE,
    ),
    "formats": QueryType.collection(
        FORMAT_RECORD_TYPE,
        ordering=CollectionOrdering.UNKNOWN,
    ),
    "chapters": QueryType.collection(
        CHAPTER_RECORD_TYPE,
        ordering=CollectionOrdering.UNKNOWN,
    ),
    "thumbnails": QueryType.collection(
        THUMBNAIL_RECORD_TYPE,
        ordering=CollectionOrdering.UNKNOWN,
    ),
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
    resolved_type: QueryType | None = None

    def __post_init__(self) -> None:
        if self.resolved_type is None:
            return
        if self.resolved_type.kind != self.kind:
            raise ValueError("Field kind must match its resolved yt-sql type.")
        if self.resolved_type.nullable != self.nullable:
            raise ValueError("Field NULLability must match its resolved yt-sql type.")

    @property
    def query_type(self) -> QueryType:
        """Return the complete resolved yt-sql type for this field."""
        if self.resolved_type is not None:
            return self.resolved_type
        return QueryType.scalar(self.kind, nullable=self.nullable)


def _infer_dynamic_value_type(
    name: str,
    values: Iterable[Any],
    *,
    nullable: bool,
) -> QueryType | None:
    """Infer one provider-derived value type without weakening yt-sql boundaries.

    Dynamic ``raw.*`` structure is inferred only when every observed non-NULL value has
    one compatible runtime shape. Mixed scalar/container shapes and heterogeneous
    container kinds remain unresolved rather than being coerced into a portable type.
    """
    values = tuple(values)
    concrete = [value for value in values if value is not None]
    if not concrete:
        return QueryType.scalar("unknown", nullable=True)
    if all(isinstance(value, dict) for value in concrete):
        return infer_dynamic_structured_type(concrete, nullable=nullable)
    if any(isinstance(value, dict) for value in concrete):
        return None
    if all(isinstance(value, (list, tuple, set)) for value in concrete):
        return infer_collection_type(
            name,
            values,
            nullable=nullable,
            allow_structured_elements=True,
        )
    if any(isinstance(value, (list, tuple, set)) for value in concrete):
        return None
    if not all(isinstance(value, SCALAR_TYPES) for value in concrete):
        return None
    kind = infer_kind(name, values)
    if kind in {"mixed", "structured"}:
        return None
    return QueryType.scalar(kind, nullable=nullable)


def infer_dynamic_structured_type(
    values: Iterable[dict[str, Any]],
    *,
    nullable: bool,
) -> QueryType:
    """Infer a conservative dynamic member schema from provider dictionaries.

    Only string-keyed members with one compatible observed value shape are exposed. A
    member missing from some records is nullable. Incompatible members are deliberately
    omitted, so attempts to use them fail during semantic resolution instead of silently
    becoming ``mixed`` scalar values. If no member can be typed safely, the structure
    remains opaque.
    """
    records = tuple(values)
    if not records or any(not all(isinstance(key, str) for key in record) for record in records):
        return QueryType.structured_opaque(nullable=nullable)

    members: list[StructuredMember] = []
    names = sorted({key for record in records for key in record})
    for member_name in names:
        present_values = [record[member_name] for record in records if member_name in record]
        member_nullable = len(present_values) < len(records) or any(value is None for value in present_values)
        member_type = _infer_dynamic_value_type(
            member_name,
            present_values,
            nullable=member_nullable,
        )
        if member_type is None:
            continue
        members.append(StructuredMember(member_name, member_type))

    if not members:
        return QueryType.structured_opaque(nullable=nullable)
    return QueryType.structured(
        members,
        nullable=nullable,
        shape=StructuredShape.DYNAMIC,
    )


def infer_collection_type(
    name: str,
    values: Iterable[Any],
    *,
    nullable: bool,
    allow_structured_elements: bool = False,
) -> QueryType | None:
    """Infer a collection type conservatively from observed runtime values.

    Provider-derived structured elements are admitted only for dynamic ``raw.*`` paths.
    Their members are inferred recursively when all observed records have compatible
    shapes; otherwise the element stays opaque rather than gaining accidental scalar
    semantics.
    """
    concrete = [value for value in values if value is not None]
    if not concrete or not all(isinstance(value, (list, tuple, set)) for value in concrete):
        return None
    ordering = (
        CollectionOrdering.UNORDERED if any(isinstance(value, set) for value in concrete) else CollectionOrdering.STABLE
    )
    elements = [element for value in concrete for element in value]
    element_concrete = [element for element in elements if element is not None]
    element_nullable = any(element is None for element in elements)
    if element_concrete and all(isinstance(element, (list, tuple, set)) for element in element_concrete):
        element_type = infer_collection_type(
            name,
            elements,
            nullable=element_nullable,
            allow_structured_elements=allow_structured_elements,
        )
        if element_type is None:
            return None
    elif any(isinstance(element, (list, tuple, set)) for element in element_concrete):
        return None
    elif (
        allow_structured_elements
        and element_concrete
        and all(isinstance(element, dict) for element in element_concrete)
    ):
        element_type = infer_dynamic_structured_type(
            element_concrete,
            nullable=element_nullable,
        )
    elif any(isinstance(element, dict) for element in element_concrete):
        return None
    else:
        element_type = QueryType.scalar(
            infer_kind(name, elements) if elements else "unknown",
            nullable=element_nullable,
        )
    return QueryType.collection(element_type, nullable=nullable, ordering=ordering)


class QuerySchema:
    """Resolve known, aliased, dynamic, and raw nested metadata fields."""

    def __init__(self, records: Iterable[dict[str, Any]]) -> None:
        self.records = tuple(records)
        self._fields: dict[str, FieldInfo] = {}
        self._logical_fields: tuple[FieldInfo, ...] | None = None
        self._build()

    @classmethod
    def from_field_infos(cls, fields: Iterable[FieldInfo]) -> "QuerySchema":
        """Construct a logical schema from already resolved query-result columns."""
        instance = cls.__new__(cls)
        instance.records = ()
        logical_fields = tuple(fields)
        instance._fields = {field.name.casefold(): field for field in logical_fields}
        instance._logical_fields = logical_fields
        return instance

    def _build(self) -> None:
        for name, kind in KNOWN_FIELD_TYPES.items():
            nullable = any(record.get(name) is None for record in self.records) or not self.records
            self._fields[name.casefold()] = FieldInfo(name, kind, nullable, dynamic=False)

        for name, declared_type in KNOWN_COLLECTION_TYPES.items():
            nullable = any(record.get(name) is None for record in self.records) or not self.records
            resolved_type = declared_type.with_nullable(nullable)
            self._fields[name.casefold()] = FieldInfo(
                name, "collection", nullable, dynamic=False, resolved_type=resolved_type
            )

        observed: dict[str, list[Any]] = {}
        for record in self.records:
            for name, value in record.items():
                if name.startswith("_"):
                    continue
                if isinstance(value, SCALAR_TYPES + (list, tuple, set)):
                    observed.setdefault(name, []).append(value)

        for name, values in observed.items():
            key = name.casefold()
            canonical = self._fields.get(key)
            if canonical is not None:
                continue
            nullable = any(value is None for value in values) or len(values) < len(self.records)
            collection_type = infer_collection_type(name, values, nullable=nullable)
            if collection_type is not None:
                self._fields[key] = FieldInfo(name, "collection", nullable, dynamic=True, resolved_type=collection_type)
                continue
            kind = infer_kind(name, values)
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
            nullable = present < len(self.records) or any(v is None for v in values)
            collection_type = infer_collection_type(path.split(".")[-1], values, nullable=nullable)
            if collection_type is not None:
                return FieldInfo(name, "collection", nullable, dynamic=True, resolved_type=collection_type)
            concrete = [value for value in values if value is not None]
            if concrete and all(isinstance(value, dict) for value in concrete):
                structured_type = infer_dynamic_structured_type(concrete, nullable=nullable)
                return FieldInfo(
                    name,
                    "structured",
                    nullable,
                    dynamic=True,
                    resolved_type=structured_type,
                )
            kind = "structured" if structured else infer_kind(path.split(".")[-1], values)
            return FieldInfo(name, kind, nullable, dynamic=True)
        return self._fields.get(lowered)

    def resolve_index_operand(self, name: str) -> FieldInfo | None:
        """Resolve a field specifically for collection indexing.

        Ordinary ``raw.*`` resolution keeps arrays of records non-selectable as whole
        structured values. Indexing may recognise such an array as an ordered provider
        sequence and infer a conservative dynamic member schema for compatible records.
        """
        field = self.resolve(name)
        if field is None or field.kind != "structured" or not name.casefold().startswith("raw."):
            return field
        path = name[4:]
        values: list[Any] = []
        present = 0
        for record in self.records:
            found, value = raw_path_value(record, path)
            if not found:
                continue
            present += 1
            values.append(value)
        if present == 0:
            return field
        nullable = present < len(self.records) or any(value is None for value in values)
        collection_type = infer_collection_type(
            path.split(".")[-1],
            values,
            nullable=nullable,
            allow_structured_elements=True,
        )
        if collection_type is None:
            return field
        return FieldInfo(name, "collection", nullable, dynamic=True, resolved_type=collection_type)

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
        if self._logical_fields is not None:
            return list(self._logical_fields)
        builtins = [self._fields[name.casefold()] for name in KNOWN_FIELD_TYPES]
        builtin_keys = {info.name.casefold() for info in builtins}
        dynamic = sorted(
            (
                info
                for info in self._fields.values()
                if info.dynamic
                and info.kind != "collection"
                and info.alias_of is None
                and info.name.casefold() not in builtin_keys
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
    if lowered in KNOWN_COLLECTION_TYPES:
        return "collection"
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
