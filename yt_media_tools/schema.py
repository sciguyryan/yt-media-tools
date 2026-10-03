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

    Provider-derived structure is inferred only when every observed non-NULL value has
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

    Provider-derived structured elements are admitted only where the caller explicitly
    permits them. Their members are inferred recursively when observed records have compatible
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
    """Resolve known, aliased and observed top-level metadata fields."""

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
        instance._fields = {field.name: field for field in logical_fields}
        instance._logical_fields = logical_fields
        return instance

    def _build(self) -> None:
        for name, kind in KNOWN_FIELD_TYPES.items():
            nullable = any(record.get(name) is None for record in self.records) or not self.records
            self._fields[name] = FieldInfo(name, kind, nullable, dynamic=False)

        for name, declared_type in KNOWN_COLLECTION_TYPES.items():
            nullable = any(record.get(name) is None for record in self.records) or not self.records
            resolved_type = declared_type.with_nullable(nullable)
            self._fields[name] = FieldInfo(name, "collection", nullable, dynamic=False, resolved_type=resolved_type)

        observed: dict[str, list[Any]] = {}
        for record in self.records:
            for name, value in record.items():
                if name.startswith("_"):
                    continue
                if isinstance(value, SCALAR_TYPES + (list, tuple, set)):
                    observed.setdefault(name, []).append(value)

        for name, values in observed.items():
            key = name
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
            target_info = self._fields.get(target)
            if target_info is not None:
                self._fields[alias] = FieldInfo(
                    alias,
                    target_info.kind,
                    target_info.nullable,
                    alias_of=target_info.name,
                    dynamic=False,
                )

    def resolve(self, name: str) -> FieldInfo | None:
        """Resolve one field from the registered or observed query schema."""
        return self._fields.get(name)

    def resolve_index_operand(self, name: str) -> FieldInfo | None:
        """Resolve a field specifically for collection indexing."""
        return self.resolve(name)

    def available_fields(self) -> list[FieldInfo]:
        """Return visible fields in deterministic display order."""
        unique: dict[tuple[str, str | None], FieldInfo] = {}
        for info in self._fields.values():
            unique[(info.name, info.alias_of)] = info
        return sorted(unique.values(), key=lambda item: (item.alias_of is not None, item.name.casefold()))

    def select_star_fields(self) -> list[FieldInfo]:
        """Return the deterministic scalar field set expanded by ``SELECT *``.

        Canonical built-in fields retain ``KNOWN_FIELD_TYPES`` declaration order.
        Observed top-level dynamic scalar fields follow in case-insensitive lexical
        order. Aliases are excluded so star expansion does not duplicate values.
        """
        if self._logical_fields is not None:
            return list(self._logical_fields)
        builtins = [self._fields[name] for name in KNOWN_FIELD_TYPES]
        builtin_keys = {info.name for info in builtins}
        dynamic = sorted(
            (
                info
                for info in self._fields.values()
                if info.dynamic
                and info.kind != "collection"
                and info.alias_of is None
                and info.name not in builtin_keys
            ),
            key=lambda item: item.name.casefold(),
        )
        return builtins + dynamic


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
