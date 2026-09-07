from __future__ import annotations

import json
import subprocess


def enumerate_source(source: str) -> list[dict[str, object]]:
    """Enumerate a YouTube source using yt-dlp's flat playlist output."""
    command = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        source,
    ]

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "yt-dlp failed"
        raise RuntimeError(message)

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("yt-dlp returned invalid JSON") from exc

    entries = data.get("entries") or []
    return [entry for entry in entries if isinstance(entry, dict)]
