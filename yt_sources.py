from __future__ import annotations

import json
import pathlib
import shutil
import subprocess


SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
YOUTUBEJS_BRIDGE = SCRIPT_DIR / "youtubejs_bridge.mjs"


def yt_dlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def youtubejs_available() -> tuple[bool, str]:
    node = shutil.which("node")
    if node is None:
        return False, "node was not found"
    if not YOUTUBEJS_BRIDGE.is_file():
        return False, "bridge script is missing"

    completed = subprocess.run(
        [node, str(YOUTUBEJS_BRIDGE), "--probe"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or "youtubei.js could not be loaded"
        return False, detail

    return True, completed.stdout.strip() or "youtubei.js"


def backend_status() -> list[tuple[str, bool, str]]:
    youtubejs_ok, youtubejs_detail = youtubejs_available()
    return [
        (
            "yt-dlp",
            yt_dlp_available(),
            "yt-dlp executable" if yt_dlp_available() else "yt-dlp was not found",
        ),
        ("youtubejs", youtubejs_ok, youtubejs_detail),
    ]


def enumerate_yt_dlp(source: str, limit: int | None = None) -> list[dict[str, object]]:
    command = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
    ]
    if limit is not None:
        command.extend(["--playlist-end", str(limit)])
    command.append(source)

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


def enumerate_youtubejs(source: str) -> list[dict[str, object]]:
    available, detail = youtubejs_available()
    if not available:
        raise RuntimeError(f"YouTube.js backend is unavailable: {detail}")

    node = shutil.which("node")
    assert node is not None

    completed = subprocess.run(
        [node, str(YOUTUBEJS_BRIDGE), source],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "YouTube.js enumeration failed"
        raise RuntimeError(message)

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("YouTube.js bridge returned invalid JSON") from exc

    if not isinstance(data, list):
        raise TypeError("YouTube.js bridge returned an unexpected result")

    return [entry for entry in data if isinstance(entry, dict)]


def fetch_details_yt_dlp(video_ids: list[str]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for video_id in video_ids:
        completed = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--dump-single-json",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            # A private, deleted or otherwise inaccessible item cannot be
            # enriched, but it must not abort refresh of the remaining IDs.
            continue
        try:
            entry = json.loads(completed.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def fetch_details_youtubejs(video_ids: list[str]) -> list[dict[str, object]]:
    available, detail = youtubejs_available()
    if not available:
        raise RuntimeError(f"YouTube.js backend is unavailable: {detail}")

    node = shutil.which("node")
    assert node is not None
    completed = subprocess.run(
        [node, str(YOUTUBEJS_BRIDGE), "--details", *video_ids],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or "YouTube.js detail refresh failed"
        raise RuntimeError(message)

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("YouTube.js bridge returned invalid detail JSON") from exc

    return [entry for entry in data if isinstance(entry, dict)]


def fetch_details(video_ids: list[str], backend: str) -> list[dict[str, object]]:
    if backend == "yt-dlp":
        return fetch_details_yt_dlp(video_ids)
    if backend == "youtubejs":
        return fetch_details_youtubejs(video_ids)
    raise RuntimeError(f"unknown source backend: {backend}")


def enumerate_source(
    source: str,
    backend: str = "yt-dlp",
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Enumerate a source using the selected backend."""
    if backend == "yt-dlp":
        return enumerate_yt_dlp(source, limit=limit)
    if backend == "youtubejs":
        return enumerate_youtubejs(source)
    raise RuntimeError(f"unknown source backend: {backend}")
