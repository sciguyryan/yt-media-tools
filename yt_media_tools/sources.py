"""YouTube source classification and URL normalisation."""

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

_CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{20,}")
# YouTube uses several playlist families. These prefixes are intentionally limited to
# recognisable collection identifiers rather than treating every arbitrary token as a playlist.
_PLAYLIST_ID_RE = re.compile(r"(?:PL|UU|LL|FL|RD|UL|TL|OLAK5uy_)[A-Za-z0-9_-]{8,}")


@dataclass(frozen=True)
class SourceSpec:
    """Resolved input source used by the acquisition layer."""

    kind: str
    original: str
    canonical_url: str
    identifier: str | None = None


def resolve_source(value: str, *, source_type: str = "auto", tab: str = "all") -> SourceSpec:
    """Classify a channel or playlist source without network-driven guessing."""
    text = value.strip()
    if not text:
        raise ValueError("SOURCE cannot be empty")
    if source_type not in {"auto", "channel", "playlist"}:
        raise ValueError(f"unknown source type: {source_type}")
    if tab not in TAB_SUFFIXES:
        raise ValueError(f"unknown channel tab: {tab}")

    if source_type == "playlist":
        spec = _resolve_as_playlist(text)
    elif source_type == "channel":
        spec = _resolve_as_channel(text, tab)
    else:
        if text.startswith(("http://", "https://")):
            spec = _resolve_url(text, tab)
        elif _CHANNEL_ID_RE.fullmatch(text):
            spec = _channel_from_id(text, tab)
        elif _PLAYLIST_ID_RE.fullmatch(text):
            spec = _playlist_from_id(text)
        else:
            spec = _resolve_as_channel(text, tab)

    if spec.kind == "playlist" and tab != "all":
        raise ValueError("--tab applies only to channel sources")
    return spec


def _resolve_url(value: str, tab: str) -> SourceSpec:
    parts = urlsplit(value)
    host = parts.netloc.lower().split(":", 1)[0]
    if host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        raise ValueError("SOURCE URL must be a YouTube URL")

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
    return _resolve_as_channel(value, tab)


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


def _resolve_as_channel(value: str, tab: str) -> SourceSpec:
    if _CHANNEL_ID_RE.fullmatch(value):
        return _channel_from_id(value, tab)
    if value.startswith("@"):
        base = f"{YOUTUBE_BASE_URL}/{value}"
        return SourceSpec("channel", value, _append_tab(base, tab), value)
    if re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        base = f"{YOUTUBE_BASE_URL}/@{value}"
        return SourceSpec("channel", value, _append_tab(base, tab), value)
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
        return SourceSpec("channel", value, _append_tab(base, tab), None)
    raise ValueError("SOURCE must be a YouTube channel/playlist URL, @handle, channel ID, playlist ID, or bare handle")


def _channel_from_id(channel_id: str, tab: str) -> SourceSpec:
    base = f"{YOUTUBE_BASE_URL}/channel/{channel_id}"
    return SourceSpec("channel", channel_id, _append_tab(base, tab), channel_id)


def _append_tab(base: str, tab: str) -> str:
    suffix = TAB_SUFFIXES[tab]
    if suffix is None:
        return base.rstrip("/")
    return f"{base.rstrip('/')}/{suffix}"
