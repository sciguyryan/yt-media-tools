"""Stable source, facet and acquisition capability declarations."""

from __future__ import annotations

from dataclasses import dataclass

from .schema import KNOWN_FIELD_TYPES
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


@dataclass(frozen=True)
class FacetCapabilities:
    """Capabilities Discover may rely on for one logical source collection."""

    name: str | None
    logical_schema: tuple[LogicalField, ...]
    stable_collection: bool
    trustworthy_order_field: str | None
    cheaply_enumerates_identities: bool
    field_overrides: tuple[FieldCapability, ...] = ()

    def field(self, name: str) -> FieldCapability:
        """Return the source/facet-specific acquisition declaration for a logical field."""
        key = name.casefold()
        for capability in self.field_overrides:
            if capability.field.casefold() == key:
                return capability
        return field_capability(name)


@dataclass(frozen=True)
class SourceCapabilities:
    """Adapter-scoped logical collections and their stable acquisition contracts."""

    adapter: str
    facets: tuple[str, ...] = ()
    default_facet: str | None = None
    facet_profiles: tuple[FacetCapabilities, ...] = ()

    def supports(self, facet: str) -> bool:
        """Return whether this source advertises the requested logical facet."""
        return facet.casefold() in self.facets

    def facet_capabilities(self, facet: str | None = None) -> FacetCapabilities:
        """Return the declared capability contract for a selected logical collection."""
        selected = self.default_facet if facet is None else facet.casefold()
        for profile in self.facet_profiles:
            if profile.name == selected:
                return profile
        label = selected if selected is not None else "default"
        raise ValueError(f"adapter {self.adapter!r} does not advertise facet {label!r}")


_STABLE_SCHEMA = tuple(
    LogicalField(name, kind, nullable=name not in {"id", "source_index"}) for name, kind in KNOWN_FIELD_TYPES.items()
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
    adapter="youtube-channel",
    facets=YOUTUBE_CHANNEL_FACETS,
    facet_profiles=(_facet_profile(None),) + tuple(_facet_profile(name) for name in YOUTUBE_CHANNEL_FACETS),
)
_YOUTUBE_PLAYLIST_CAPABILITIES = SourceCapabilities(
    adapter="youtube-playlist",
    facet_profiles=(_facet_profile(None),),
)
_GENERIC_YTDLP_CAPABILITIES = SourceCapabilities(
    adapter="yt-dlp-generic",
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
    adapter="unknown",
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
    "extractor": _GENERIC_YTDLP_CAPABILITIES,
}


def source_capabilities(source: SourceSpec) -> SourceCapabilities:
    """Translate classified source identity into a stable adapter capability contract."""
    return _SOURCE_CAPABILITIES_BY_KIND.get(source.kind, _UNKNOWN_CAPABILITIES)


def selected_facet_capabilities(source: SourceSpec) -> FacetCapabilities:
    """Return the capability contract for the logical collection selected by ``source``."""
    return source_capabilities(source).facet_capabilities(source.facet)


def logical_source_identity(source: SourceSpec) -> LogicalSourceIdentity:
    """Return physical/logical identity without leaking adapter-specific details to callers."""
    capabilities = source_capabilities(source)
    physical_url = source.canonical_url
    if source.kind == "channel" and source.facet is not None:
        suffix = "/" + YOUTUBE_CHANNEL_FACET_SUFFIXES[source.facet]
        if physical_url.endswith(suffix):
            physical_url = physical_url[: -len(suffix)]
    physical = PhysicalSourceIdentity(source.kind, capabilities.adapter, physical_url, source.identifier)
    return LogicalSourceIdentity(physical, source.canonical_url, source.facet)
