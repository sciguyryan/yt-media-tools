"""yt-dlp bridge for Downloader's versioned collection interchange.

This postprocessor is loaded only for ``--collection-file`` runs.  It injects the
small, explicit playlist metadata contract before yt-dlp renders output templates;
it is not a general metadata mutation plugin.
"""

from __future__ import annotations

import base64
import json
from collections import defaultdict, deque
from pathlib import Path

from yt_dlp.postprocessor.common import PostProcessor


class CollectionMetadataPP(PostProcessor):
    """Inject typed playlist context for one ordered Downloader collection."""

    def __init__(self, downloader=None, collection=None, **kwargs):
        super().__init__(downloader)
        if not collection:
            raise ValueError("CollectionMetadata requires a collection path")
        try:
            path = Path(base64.urlsafe_b64decode(collection.encode("ascii")).decode("utf-8"))
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"unable to load Downloader collection metadata: {exc}") from exc
        self._metadata = payload["collection"]["metadata"]
        self._count = len(payload["entries"])
        self._positions = defaultdict(deque)
        for position, entry in enumerate(payload["entries"], start=1):
            self._positions[entry["target"]].append(position)

    def _position_for(self, info):
        """Resolve the original acquisition target to its stable collection position."""
        candidates = (info.get("original_url"), info.get("webpage_url"), info.get("id"))
        for candidate in candidates:
            positions = self._positions.get(candidate)
            if positions:
                return positions.popleft()
        raise ValueError("yt-dlp returned media which cannot be associated with an entry in the supplied collection")

    def run(self, info):
        """Apply the supported collection fields and leave all other metadata alone."""
        position = self._position_for(info)
        supplied = {
            "playlist_title": "title",
            "playlist_id": "id",
            "playlist_uploader": "uploader",
            "playlist_uploader_id": "uploader_id",
            "playlist_channel": "channel",
            "playlist_channel_id": "channel_id",
            "playlist_webpage_url": "webpage_url",
        }
        for yt_dlp_field, interchange_key in supplied.items():
            if interchange_key in self._metadata:
                info[yt_dlp_field] = self._metadata[interchange_key]

        title = self._metadata.get("title")
        playlist_id = self._metadata.get("id")
        if title is not None or playlist_id is not None:
            info["playlist"] = title if title is not None else playlist_id

        info["playlist_index"] = position
        info["playlist_autonumber"] = position
        info["playlist_count"] = self._count
        info["n_entries"] = self._count
        return [], info
