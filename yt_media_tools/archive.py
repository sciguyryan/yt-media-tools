"""Helpers for yt-dlp download archive files."""

from __future__ import annotations

from pathlib import Path


def read_archive_ids(path: Path) -> set[str]:
    """Read video IDs from yt-dlp's normal two-column archive format."""
    ids: set[str] = set()
    with path.open("r", encoding="utf-8", errors="replace") as stream:
        for line in stream:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts:
                ids.add(parts[-1])
    return ids


def exclude_archive(records: list[dict], archive_ids: set[str]) -> list[dict]:
    return [record for record in records if str(record.get("id", "")) not in archive_ids]
