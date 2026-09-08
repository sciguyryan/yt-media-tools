"""Source classification, capability discovery, and acquisition-target resolution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, urlsplit, urlunsplit


YOUTUBE_BASE_URL = "https://www.youtube.com"

TAB_SUFFIXES = {
    "all": None,
    "videos": "videos",
    "shorts": "shorts",
    "live": "streams",
}
KNOWN_TAB_SUFFIXES = frozenset({"videos", "shorts", "streams", "featured"})
YOUTUBE_CHANNEL_FACETS = ("videos", "shorts", "live")

_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{20,}")
# YouTube uses several playlist families. These prefixes are intentionally limited to
# recognisable collection identifiers rather than treating every arbitrary token as a playlist.
_PLAYLIST_ID_RE = re.compile(r"(?:PL|UU|LL|FL|RD|UL|TL|OLAK5uy_)[A-Za-z0-9_-]{8,}")


@dataclass(frozen=True)
class SourceSpec:
    """Resolved physical source and, when selected, its logical facet."""

    kind: str
    original: str
    canonical_url: str
    identifier: str | None = None
    facet: str | None = None


@dataclass(frozen=True)
class SourceCapabilities:
    """Logical collections advertised by one classified physical source.

    ``default_facet`` is ``None`` when the bare source is itself the default
    collection. ``facets`` contains only explicit names that may appear after
    yt-sql ``OF``. The core query layer consumes this contract without needing
    extractor-specific URL or command knowledge.
    """

    adapter: str
    facets: tuple[str, ...] = ()
    default_facet: str | None = None

    def supports(self, facet: str) -> bool:
        """Return whether this source advertises the requested logical facet."""
        return facet.casefold() in self.facets


def source_capabilities(source: SourceSpec) -> SourceCapabilities:
    """Return deterministic logical capabilities for a classified source.

    Capability discovery is deliberately conservative. Known YouTube channel
    sources advertise stable logical channel collections. Playlists and generic
    yt-dlp extractor URLs currently expose only their default collection until a
    dedicated adapter can make stronger promises.
    """
    if source.kind == "channel":
        return SourceCapabilities("youtube-channel", YOUTUBE_CHANNEL_FACETS)
    if source.kind == "playlist":
        return SourceCapabilities("youtube-playlist")
    if source.kind == "extractor":
        return SourceCapabilities("yt-dlp-generic")
    return SourceCapabilities("unknown")


def resolve_source_request(
    value: str,
    *,
    facet: str | None = None,
    source_type: str = "auto",
    tab: str = "all",
) -> SourceSpec:
    """Resolve one source request through the shared facet capability model.

    ``--tab`` remains a compatibility input only. It is translated into the
    same logical facet request used by yt-sql ``OF`` before capability
    validation. No separate tab-specific acquisition path exists here.
    """
    requested = _normalise_requested_facet(facet=facet, tab=tab)
    classified = _classify_source(value, source_type=source_type)
    if requested is None:
        return classified

    capabilities = source_capabilities(classified)
    if not capabilities.supports(requested):
        advertised = ", ".join(capabilities.facets) or "none"
        compatibility = "compatibility option --tab requested this facet; " if facet is None and tab != "all" else ""
        raise ValueError(
            f"{compatibility}source {value!r} does not advertise facet {requested!r}; "
            f"adapter {capabilities.adapter!r} advertises: {advertised}"
        )
    return _apply_facet(classified, requested)


def resolve_source(value: str, *, source_type: str = "auto", tab: str = "all") -> SourceSpec:
    """Compatibility resolver preserving the established ``--tab`` API."""
    return resolve_source_request(value, source_type=source_type, tab=tab)


def _normalise_requested_facet(*, facet: str | None, tab: str) -> str | None:
    """Merge yt-sql OF and legacy --tab into one canonical logical request."""
    if tab not in TAB_SUFFIXES:
        raise ValueError(f"unknown channel tab: {tab}")
    requested = facet.casefold() if facet is not None else None
    compatibility = None if tab == "all" else tab
    if requested is not None and compatibility is not None and requested != compatibility:
        raise ValueError(f"source facet OF {requested} conflicts with compatibility option --tab {tab}")
    return requested or compatibility


def _classify_source(value: str, *, source_type: str) -> SourceSpec:
    """Classify a physical source without applying any collection/facet choice."""
    text = value.strip()
    if not text:
        raise ValueError("SOURCE cannot be empty")
    if source_type not in {"auto", "channel", "playlist"}:
        raise ValueError(f"unknown source type: {source_type}")

    if source_type == "playlist":
        return _resolve_as_playlist(text)
    if source_type == "channel":
        return _resolve_as_channel(text)
    if text.startswith(("http://", "https://")):
        return _resolve_url(text)
    if _CHANNEL_ID_RE.fullmatch(text):
        return _channel_from_id(text)
    if _PLAYLIST_ID_RE.fullmatch(text):
        return _playlist_from_id(text)
    return _resolve_as_channel(text)


def _resolve_url(value: str) -> SourceSpec:
    parts = urlsplit(value)
    host = parts.netloc.lower().split(":", 1)[0]
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        return SourceSpec("extractor", value, value, None)

    query = parse_qs(parts.query)
    playlist_ids = query.get("list", [])
    if playlist_ids:
        playlist_id = playlist_ids[0].strip()
        if not playlist_id:
            raise ValueError("playlist URL contains an empty list parameter")
        return _playlist_from_id(playlist_id, original=value)

    path_parts = [part for part in parts.path.split("/") if part]
    if host == "youtu.be" or (path_parts and path_parts[0] in {"watch", "shorts", "embed"}):
        raise ValueError("SOURCE must identify a channel or playlist, not an individual video")
    return _resolve_as_channel(value)


def _resolve_as_playlist(value: str) -> SourceSpec:
    if value.startswith(("http://", "https://")):
        parts = urlsplit(value)
        host = parts.netloc.lower().split(":", 1)[0]
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("playlist URL must be a YouTube URL")
        playlist_ids = parse_qs(parts.query).get("list", [])
        if not playlist_ids or not playlist_ids[0].strip():
            raise ValueError("playlist URL must contain a non-empty list parameter")
        return _playlist_from_id(playlist_ids[0].strip(), original=value)
    return _playlist_from_id(value)


def _playlist_from_id(playlist_id: str, original: str | None = None) -> SourceSpec:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,}", playlist_id):
        raise ValueError("playlist ID contains unsupported characters or is unexpectedly short")
    url = f"{YOUTUBE_BASE_URL}/playlist?list={quote(playlist_id, safe='_-')}"
    return SourceSpec("playlist", original or playlist_id, url, playlist_id)


def _resolve_as_channel(value: str) -> SourceSpec:
    if _CHANNEL_ID_RE.fullmatch(value):
        return _channel_from_id(value)
    if value.startswith("@"):
        return SourceSpec("channel", value, f"{YOUTUBE_BASE_URL}/{value}", value)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        return SourceSpec("channel", value, f"{YOUTUBE_BASE_URL}/@{value}", value)
    if value.startswith(("http://", "https://")):
        parts = urlsplit(value)
        host = parts.netloc.lower().split(":", 1)[0]
        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            raise ValueError("channel URL must be a YouTube URL")
        path_parts = [part for part in parts.path.split("/") if part]
        if not path_parts:
            raise ValueError("channel URL does not contain a channel")
        if path_parts[0] in {"watch", "playlist", "shorts", "embed"}:
            raise ValueError("SOURCE must identify a channel, not a video or playlist")
        if path_parts[-1].casefold() in KNOWN_TAB_SUFFIXES:
            path_parts.pop()
        if not path_parts:
            raise ValueError("channel URL does not contain a channel")
        base_path = "/" + "/".join(path_parts)
        base = urlunsplit(("https", "www.youtube.com", base_path, "", ""))
        return SourceSpec("channel", value, base, None)
    raise ValueError("SOURCE must be a YouTube channel/playlist URL, @handle, channel ID, playlist ID, or bare handle")


def _channel_from_id(channel_id: str) -> SourceSpec:
    return SourceSpec("channel", channel_id, f"{YOUTUBE_BASE_URL}/channel/{channel_id}", channel_id)


def _apply_facet(source: SourceSpec, facet: str) -> SourceSpec:
    """Map an advertised logical facet onto the adapter's physical target."""
    if source.kind != "channel":
        raise AssertionError(f"no facet mapper exists for source kind {source.kind!r}")
    suffix = TAB_SUFFIXES[facet]
    if suffix is None:
        raise AssertionError("explicit facets must map to a physical suffix")
    return SourceSpec(
        source.kind,
        source.original,
        f"{source.canonical_url.rstrip('/')}/{suffix}",
        source.identifier,
        facet,
    )
