"""Production ytmusicapi metadata acquisition for conservatively resolved music sources."""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

from .external_tools import ToolInvocation, emit_invocation
from .ytdlp import AcquisitionStats


class YtMusicApiError(RuntimeError):
    """Raised when the optional ytmusicapi production capability cannot run."""


def _current_signature_timestamp() -> int:
    """Return the current day-based signature timestamp expected by ytmusicapi."""
    return (date.today() - date(1970, 1, 1)).days


def _integer(value: object) -> int | None:
    """Convert a provider scalar to an integer without broad coercion."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def acquire_song_metadata(video_ids: list[str]) -> tuple[list[dict[str, Any]], AcquisitionStats]:
    """Acquire the production-authorised exact scalar surface through ``YTMusic.get_song``.

    Eligibility is established by the caller from independent source evidence. Provider-native
    music signals returned here therefore cannot authorise this operation retrospectively.
    """
    if not video_ids:
        return [], AcquisitionStats()
    try:
        module = importlib.import_module("ytmusicapi")
    except ImportError as exc:
        raise YtMusicApiError("ytmusicapi is not installed") from exc
    try:
        client = module.YTMusic()
    except Exception as exc:  # noqa: BLE001 - third-party construction is an integration boundary.
        raise YtMusicApiError(f"could not initialise ytmusicapi: {exc}") from exc

    signature_timestamp = _current_signature_timestamp()
    records: list[dict[str, Any]] = []
    stats = AcquisitionStats()
    for video_id in video_ids:
        emit_invocation(
            ToolInvocation(
                tool="ytmusicapi",
                operation="YTMusic.get_song",
                purpose="authoritative specialised music metadata acquisition",
                arguments={
                    "video_id": video_id,
                    "authentication": "anonymous",
                    "signature_timestamp": signature_timestamp,
                },
            )
        )
        try:
            payload = client.get_song(video_id, signatureTimestamp=signature_timestamp)
        except Exception:  # noqa: BLE001 - individual provider failures fall back conservatively.
            stats.record_skip(video_id, "ytmusicapi-error")
            continue
        if not isinstance(payload, dict):
            stats.record_skip(video_id, "ytmusicapi-error")
            continue
        details = payload.get("videoDetails")
        if not isinstance(details, dict):
            stats.record_skip(video_id, "ytmusicapi-error")
            continue
        title = details.get("title")
        channel_id = details.get("channelId")
        if not isinstance(title, str) or not title or not isinstance(channel_id, str) or not channel_id:
            stats.record_skip(video_id, "ytmusicapi-error")
            continue
        records.append(
            {
                "id": video_id,
                "title": title,
                "channel_id": channel_id,
                "duration": _integer(details.get("lengthSeconds")),
                "view_count": _integer(details.get("viewCount")),
                "_yt_sql_metadata_provider": "ytmusicapi",
                "_yt_sql_metadata_operation": "YTMusic.get_song",
            }
        )
        stats.available += 1
    return records, stats
