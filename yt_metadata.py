from __future__ import annotations

from datetime import UTC, datetime


def normalise_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None

    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def normalise_duration(value: object) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalise_live(entry: dict[str, object]) -> bool | None:
    value = entry.get("live_status")
    if value in {"is_live", "was_live"}:
        return True
    if isinstance(value, str):
        return False

    value = entry.get("is_live")
    if isinstance(value, bool):
        return value

    return None


def normalise_entry(entry: dict[str, object]) -> dict[str, object]:
    """Convert extractor-specific metadata to Discover's internal shape."""
    uploader = entry.get("uploader") or entry.get("channel")

    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "uploader": uploader,
        "duration": normalise_duration(entry.get("duration")),
        "date": normalise_date(entry.get("upload_date")),
        "live": normalise_live(entry),
    }


def normalise_entries(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    return [normalise_entry(entry) for entry in entries]
