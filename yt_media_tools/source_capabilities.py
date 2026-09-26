"""Stable source, facet and acquisition capability declarations."""

from __future__ import annotations

from dataclasses import dataclass

from .query_types import QueryType
from .schema import KNOWN_COLLECTION_TYPES, KNOWN_FIELD_TYPES
from .source_model import LogicalSourceIdentity, PhysicalSourceIdentity, SourceSpec


EXACT = "exact"
APPROXIMATE = "approximate"
UNAVAILABLE = "unavailable"

STRUCTURALLY_SUPPORTED = "supported"
STRUCTURALLY_UNSUPPORTED = "unsupported"
STRUCTURAL_SUPPORT_UNKNOWN = "unknown"

YOUTUBE_CHANNEL_FACET_SUFFIXES = {
    "videos": "videos",
    "shorts": "shorts",
    "live": "streams",
}
YOUTUBE_CHANNEL_FACETS = tuple(YOUTUBE_CHANNEL_FACET_SUFFIXES)


@dataclass(frozen=True)
class FieldCapability:
    """Describe stable field support and acquisition quality across metadata stages."""

    field: str
    youtubejs: str
    ytdlp_flat: str
    ytdlp_detailed: str = EXACT
    logical_kind: str | None = None
    nullable: bool = True
    structural_support: str = STRUCTURALLY_SUPPORTED
    logical_type: QueryType | None = None

    @property
    def enumeration_available(self) -> bool:
        """Return whether flat yt-dlp enumeration can provide any usable value."""
        return self.ytdlp_flat != UNAVAILABLE

    @property
    def requires_detailed_metadata(self) -> bool:
        """Return whether exact detailed metadata is stronger than enumeration metadata."""
        return self.ytdlp_detailed != UNAVAILABLE and self.ytdlp_flat != self.ytdlp_detailed


_FIELD_CAPABILITIES = {
    "id": FieldCapability("id", EXACT, EXACT, logical_kind="string", nullable=False),
    "title": FieldCapability("title", EXACT, EXACT, logical_kind="string"),
    "upload_date": FieldCapability("upload_date", APPROXIMATE, APPROXIMATE, logical_kind="date"),
    "date": FieldCapability("date", APPROXIMATE, APPROXIMATE, logical_kind="date"),
    "duration": FieldCapability("duration", UNAVAILABLE, APPROXIMATE, logical_kind="duration"),
    "view_count": FieldCapability("view_count", APPROXIMATE, APPROXIMATE, logical_kind="count"),
    "views": FieldCapability("views", APPROXIMATE, APPROXIMATE, logical_kind="count"),
    "source_index": FieldCapability("source_index", EXACT, EXACT, logical_kind="count", nullable=False),
}


@dataclass(frozen=True)
class LogicalField:
    """Stable field declaration visible before dynamic metadata is acquired."""

    name: str
    kind: str
    nullable: bool = True
    resolved_type: QueryType | None = None

    @property
    def query_type(self) -> QueryType:
        if self.resolved_type is not None:
            return self.resolved_type.with_nullable(self.nullable)
        return QueryType.scalar(self.kind, nullable=self.nullable)


@dataclass(frozen=True)
class FacetCapabilities:
    """Capabilities Discover may rely on for one logical source collection."""

    name: str | None
    logical_schema: tuple[LogicalField, ...]
    stable_collection: bool
    trustworthy_order_field: str | None
    cheaply_enumerates_identities: bool
    field_overrides: tuple[FieldCapability, ...] = ()
    exact_indexed_fields: frozenset[str] = frozenset()
    exact_member_fields: frozenset[str] = frozenset()
    exact_collection_query_fields: frozenset[str] = frozenset()

    def field(self, name: str) -> FieldCapability:
        """Return the source/facet-specific acquisition declaration for a logical field."""
        key = name.casefold()
        for capability in self.field_overrides:
            if capability.field.casefold() == key:
                return capability
        return field_capability(name)

    def supports_exact_indexed_acquisition(self, field: str) -> bool:
        """Return whether the adapter can fetch one logical collection position exactly."""
        return field.casefold() in self.exact_indexed_fields

    def supports_exact_member_acquisition(self, field: str, members: tuple[str, ...]) -> bool:
        """Return whether the adapter can fetch one structured member path exactly."""
        if not members:
            return False
        path = ".".join((field, *members)).casefold()
        return path in self.exact_member_fields

    def supports_exact_collection_query(self, field: str, operation: str) -> bool:
        """Return whether the adapter can execute one yt-sql collection operation exactly.

        The capability is intentionally operation-specific. Advertising an entry is
        a strong semantic promise that NULL handling, three-valued predicates,
        element ordering and result typing match yt-sql for the named operation.
        """
        key = f"{field}:{operation}".casefold()
        return key in self.exact_collection_query_fields


@dataclass(frozen=True)
class SourceCapabilities:
    """Source-family logical collections and their stable acquisition contracts.

    ``source_family`` identifies source-resolution semantics, not the acquisition backend.
    Backends and metadata providers are selected separately from logical source identity.
    """

    source_family: str
    facets: tuple[str, ...] = ()
    default_facet: str | None = None
    facet_profiles: tuple[FacetCapabilities, ...] = ()
    facet_target_suffixes: tuple[tuple[str, str], ...] = ()

    @property
    def adapter(self) -> str:
        """Return the legacy source-family label for compatibility with older callers."""
        return self.source_family

    def supports(self, facet: str) -> bool:
        """Return whether this source advertises the requested logical facet."""
        return facet.casefold() in self.facets

    def resolve_facet_target(self, canonical_url: str, facet: str) -> str:
        """Resolve one advertised logical facet to this source family's physical target."""
        for name, suffix in self.facet_target_suffixes:
            if name == facet.casefold():
                return f"{canonical_url.rstrip('/')}/{suffix}"
        raise ValueError(f"source family {self.source_family!r} has no physical target mapping for facet {facet!r}")

    def facet_capabilities(self, facet: str | None = None) -> FacetCapabilities:
        """Return the declared capability contract for a selected logical collection."""
        selected = self.default_facet if facet is None else facet.casefold()
        for profile in self.facet_profiles:
            if profile.name == selected:
                return profile
        label = selected if selected is not None else "default"
        raise ValueError(f"source family {self.source_family!r} does not advertise facet {label!r}")


_STABLE_SCHEMA = tuple(
    LogicalField(name, kind, nullable=name not in {"id", "source_index"}) for name, kind in KNOWN_FIELD_TYPES.items()
) + tuple(
    LogicalField(name, "collection", True, resolved_type=value_type)
    for name, value_type in KNOWN_COLLECTION_TYPES.items()
)


def _facet_profile(
    name: str | None,
    *,
    stable: bool = True,
    trustworthy_order_field: str | None = "source_index",
    cheaply_enumerates_identities: bool = True,
) -> FacetCapabilities:
    return FacetCapabilities(
        name=name,
        logical_schema=_STABLE_SCHEMA,
        stable_collection=stable,
        trustworthy_order_field=trustworthy_order_field,
        cheaply_enumerates_identities=cheaply_enumerates_identities,
    )


_YOUTUBE_CHANNEL_CAPABILITIES = SourceCapabilities(
    source_family="youtube-channel",
    facets=YOUTUBE_CHANNEL_FACETS,
    facet_profiles=(_facet_profile(None),) + tuple(_facet_profile(name) for name in YOUTUBE_CHANNEL_FACETS),
    facet_target_suffixes=tuple(YOUTUBE_CHANNEL_FACET_SUFFIXES.items()),
)
_YOUTUBE_PLAYLIST_CAPABILITIES = SourceCapabilities(
    source_family="youtube-playlist",
    facet_profiles=(_facet_profile(None),),
)
_GENERIC_YTDLP_CAPABILITIES = SourceCapabilities(
    source_family="generic-url",
    facet_profiles=(
        _facet_profile(
            None,
            stable=False,
            trustworthy_order_field=None,
            cheaply_enumerates_identities=False,
        ),
    ),
)
_UNKNOWN_CAPABILITIES = SourceCapabilities(
    source_family="unknown",
    facet_profiles=(
        _facet_profile(
            None,
            stable=False,
            trustworthy_order_field=None,
            cheaply_enumerates_identities=False,
        ),
    ),
)


def field_capability(field: str) -> FieldCapability:
    """Return the conservative stable acquisition declaration for a query field."""
    key = field.casefold()
    if key in _FIELD_CAPABILITIES:
        return _FIELD_CAPABILITIES[key]
    kind = KNOWN_FIELD_TYPES.get(key)
    if kind is not None:
        return FieldCapability(field, UNAVAILABLE, UNAVAILABLE, EXACT, logical_kind=kind)
    if key in KNOWN_COLLECTION_TYPES:
        return FieldCapability(
            field,
            UNAVAILABLE,
            UNAVAILABLE,
            EXACT,
            logical_kind="collection",
            logical_type=KNOWN_COLLECTION_TYPES[key],
        )
    # Dynamic/raw fields are not part of the stable logical schema. Detailed yt-dlp
    # metadata may expose them, but no source adapter promises that they exist.
    return FieldCapability(
        field,
        UNAVAILABLE,
        UNAVAILABLE,
        EXACT,
        logical_kind=None,
        structural_support=STRUCTURAL_SUPPORT_UNKNOWN,
    )


def capabilities_for_fields(fields: set[str]) -> list[FieldCapability]:
    """Return stable acquisition declarations for fields in deterministic order."""
    return [field_capability(field) for field in sorted(fields)]


_SOURCE_CAPABILITIES_BY_KIND = {
    "channel": _YOUTUBE_CHANNEL_CAPABILITIES,
    "playlist": _YOUTUBE_PLAYLIST_CAPABILITIES,
    "url": _GENERIC_YTDLP_CAPABILITIES,
}


def source_capabilities(source: SourceSpec) -> SourceCapabilities:
    """Translate classified source identity into a stable adapter capability contract."""
    return _SOURCE_CAPABILITIES_BY_KIND.get(source.kind, _UNKNOWN_CAPABILITIES)


def selected_facet_capabilities(source: SourceSpec) -> FacetCapabilities:
    """Return the capability contract for the logical collection selected by ``source``."""
    return source_capabilities(source).facet_capabilities(source.facet)


def logical_source_identity(source: SourceSpec) -> LogicalSourceIdentity:
    """Return physical/logical identity without leaking adapter-specific details to callers."""
    physical_url = source.canonical_url
    if source.kind == "channel" and source.facet is not None:
        suffix = "/" + YOUTUBE_CHANNEL_FACET_SUFFIXES[source.facet]
        if physical_url.endswith(suffix):
            physical_url = physical_url[: -len(suffix)]
    physical = PhysicalSourceIdentity(source.kind, physical_url, source.identifier)
    return LogicalSourceIdentity(physical, source.canonical_url, source.facet)
