from __future__ import annotations


EXACT = "exact"
APPROXIMATE = "approximate"
UNAVAILABLE = "unavailable"

BACKEND_CAPABILITIES: dict[str, dict[str, str]] = {
    "yt-dlp": {
        "id": EXACT,
        "title": EXACT,
        "uploader": EXACT,
        "duration": APPROXIMATE,
        "date": APPROXIMATE,
        "live": APPROXIMATE,
    },
    "youtubejs": {
        "id": EXACT,
        "title": EXACT,
        "uploader": EXACT,
        "duration": EXACT,
        "date": APPROXIMATE,
        "live": EXACT,
    },
}


def capability(backend: str, field: str) -> str:
    return BACKEND_CAPABILITIES.get(backend, {}).get(field, UNAVAILABLE)
