"""Optional YouTube.js channel enumeration backend."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .dates import DateContext, parse_date_literal
from .ytdlp import EnumerationStats, ProgressCallback


class YouTubeJsError(RuntimeError):
    """Raised when the optional YouTube.js backend cannot enumerate a channel."""


def _published_date(text: str, dates: DateContext) -> tuple[date, timedelta] | None:
    """Interpret relative publication text and attach a conservative uncertainty window.

    Channel cards normally expose relative text rather than an exact date. The uncertainty is
    deliberately biased towards retaining entries: an item is considered safely old only when
    even the newest plausible date remains older than the planner boundary.
    """
    cleaned = " ".join(text.strip().split())
    cleaned = re.sub(r"^(?:streamed|premiered)\s+", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return None
    try:
        parsed = parse_date_literal(cleaned, dates)
    except ValueError:
        return None

    lowered = cleaned.casefold()
    if "day" in lowered:
        uncertainty = timedelta(days=2)
    elif "week" in lowered:
        uncertainty = timedelta(days=8)
    elif "month" in lowered:
        uncertainty = timedelta(days=35)
    elif "year" in lowered:
        uncertainty = timedelta(days=370)
    else:
        uncertainty = timedelta(days=1)
    return parsed, uncertainty


def enumerate_until_date_boundary(
    project_root: Path,
    source_url: str,
    *,
    stop_before: date,
    confirmation_entries: int,
    dates: DateContext,
    progress: ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], EnumerationStats]:
    """Enumerate channel videos through YouTube.js and terminate continuation paging early."""
    node = shutil.which("node")
    bridge = project_root / "yt_media_tools" / "youtubejs_bridge.mjs"
    if node is None:
        raise YouTubeJsError("Node.js was not found in PATH")
    if not bridge.is_file():
        raise YouTubeJsError(f"YouTube.js bridge script is missing: {bridge}")

    command = [node, str(bridge), "--enumerate-channel-videos", source_url]
    try:
        process = subprocess.Popen(
            command,
            cwd=project_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YouTubeJsError(f"could not run Node.js: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    entries: list[dict[str, Any]] = []
    stats = EnumerationStats()

    def read_stderr() -> None:
        for raw_line in process.stderr:
            sys.stderr.write(raw_line)
            sys.stderr.flush()

    stderr_thread = threading.Thread(target=read_stderr, name="yt-discover-youtubejs-stderr", daemon=True)
    stderr_thread.start()

    consecutive_old = 0
    try:
        for line_number, raw_line in enumerate(process.stdout, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                process.terminate()
                process.wait()
                raise YouTubeJsError(
                    f"YouTube.js bridge emitted invalid JSON on output line {line_number}: {exc.msg}"
                ) from exc
            if not isinstance(entry, dict):
                continue
            entries.append(entry)
            stats.enumerated += 1
            stats.acquisition.available += 1
            if progress is not None:
                detail = str(entry.get("id") or f"entry {stats.enumerated}")
                progress("enumerated", stats.acquisition, detail)
            published_text = str(entry.get("published_text") or "")
            published = _published_date(published_text, dates)
            if published is None:
                stats.undated += 1
                consecutive_old = 0
            else:
                stats.dated += 1
                approximate, uncertainty = published
                entry["approximate_upload_date"] = approximate.isoformat()
                entry["approximate_upload_date_newest"] = (approximate + uncertainty).isoformat()
                entry["approximate_upload_date_oldest"] = (approximate - uncertainty).isoformat()
                if approximate + uncertainty < stop_before:
                    stats.boundary_old_entries += 1
                    consecutive_old += 1
                else:
                    consecutive_old = 0

            if consecutive_old >= confirmation_entries:
                stats.stopped_early = True
                process.terminate()
                break
    finally:
        if process.poll() is None:
            return_code = process.wait()
        else:
            return_code = process.returncode
        stderr_thread.join()

    if return_code not in (0, -15) and not stats.stopped_early:
        raise YouTubeJsError(f"YouTube.js bridge exited with status {return_code}")
    return entries, stats
