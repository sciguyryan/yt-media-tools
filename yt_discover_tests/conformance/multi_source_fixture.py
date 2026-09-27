"""Deterministic heterogeneous source relations for set-composition conformance."""

from __future__ import annotations

from copy import deepcopy


YOUTUBE_CHANNEL = "@youtube_channel"
YOUTUBE_PLAYLIST = "@youtube_playlist"
TWITCH_ARCHIVE = "@twitch_archive"


_RECORDS: tuple[dict[str, object], ...] = (
    {
        "id": "yt-channel-1",
        "title": "AMV Σ",
        "uploader": "Channel A",
        "duration": 210,
        "view_count": 1200,
        "upload_date": "20260901",
        "release_timestamp": 1788278400,
        "playlist_index": None,
        "extractor_value": 7,
        "_yt_sql_source": YOUTUBE_CHANNEL,
    },
    {
        "id": "yt-channel-2",
        "title": "AMV é",
        "uploader": "Channel A",
        "duration": None,
        "view_count": 800,
        "upload_date": "20260902",
        "release_timestamp": 1788364800,
        "playlist_index": None,
        "extractor_value": 8,
        "_yt_sql_source": YOUTUBE_CHANNEL,
    },
    {
        "id": "yt-playlist-1",
        "title": "AMV e\u0301",
        "uploader": "Channel B",
        "duration": 180,
        "view_count": 800,
        "upload_date": "20260903",
        "release_timestamp": None,
        "playlist_index": 1,
        "extractor_value": 9,
        "_yt_sql_source": YOUTUBE_PLAYLIST,
    },
    {
        "id": "shared-id",
        "title": "Shared",
        "uploader": "Channel B",
        "duration": 90,
        "view_count": 50,
        "upload_date": "20260904",
        "release_timestamp": None,
        "playlist_index": 2,
        "extractor_value": 10,
        "_yt_sql_source": YOUTUBE_PLAYLIST,
    },
    {
        "id": "twitch-1",
        "title": "AMV stream",
        "uploader": "Streamer",
        "duration": 3600,
        "view_count": None,
        "upload_date": None,
        "release_timestamp": 1788537600,
        "playlist_index": None,
        "extractor_value": "seven",
        "_yt_sql_source": TWITCH_ARCHIVE,
    },
    {
        "id": "shared-id",
        "title": "Shared",
        "uploader": "Streamer",
        "duration": 90,
        "view_count": None,
        "upload_date": None,
        "release_timestamp": 1788624000,
        "playlist_index": None,
        "extractor_value": "ten",
        "_yt_sql_source": TWITCH_ARCHIVE,
    },
)


def heterogeneous_records() -> list[dict[str, object]]:
    """Return a fresh deterministic channel, playlist and Twitch-like dataset."""
    return deepcopy(list(_RECORDS))
