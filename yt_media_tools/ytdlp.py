"""Shared yt-dlp process helpers and acquisition telemetry."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


DEFAULT_COOKIES_FILE = Path("/mnt/storage/Storage/Scripts/cookies.txt")
DEFAULT_EXTRACTOR_ARGS = "youtube:player-client=default,-android_sdkless"


class YtDlpError(RuntimeError):
    """Raised when yt-dlp cannot be executed successfully."""


@dataclass
class AcquisitionStats:
    """Counters collected while yt-dlp enumerates and extracts video metadata."""

    available: int = 0
    error_lines: int = 0
    identified_error_lines: int = 0
    skipped_by_id: dict[str, str] = field(default_factory=dict)
    skipped_categories: dict[str, int] = field(default_factory=dict)

    @property
    def skipped(self) -> int:
        return len(self.skipped_by_id)

    @property
    def attempted(self) -> int:
        """Known video attempts: successful records plus uniquely identified failures."""
        return self.available + self.skipped

    def record_skip(self, video_id: str, category: str) -> bool:
        """Record a uniquely identified skipped video, returning True for a new ID."""
        if video_id in self.skipped_by_id:
            return False
        self.skipped_by_id[video_id] = category
        self.skipped_categories[category] = self.skipped_categories.get(category, 0) + 1
        return True


ProgressCallback = Callable[[str, AcquisitionStats, str | None], None]


def shell_join(command: list[str]) -> str:
    return shlex.join(command)


def ensure_ytdlp() -> None:
    if shutil.which("yt-dlp") is None:
        raise YtDlpError("yt-dlp was not found in PATH")


def build_metadata_command(
    source_url: str,
    *,
    cookies_file: Path = DEFAULT_COOKIES_FILE,
    extractor_args: str = DEFAULT_EXTRACTOR_ARGS,
    playlist_items: str | None = None,
    date: str | None = None,
    date_after: str | None = None,
    date_before: str | None = None,
    match_filters: tuple[str, ...] = (),
) -> list[str]:
    """Build a command that emits one full JSON object per successfully extracted video."""
    command = [
        "yt-dlp",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--no-flat-playlist",
        "--dump-json",
    ]
    if cookies_file.is_file():
        command.extend(("--cookies", str(cookies_file)))
    if extractor_args:
        command.extend(("--extractor-args", extractor_args))
    if date:
        command.extend(("--date", date))
    if date_after:
        command.extend(("--dateafter", date_after))
    if date_before:
        command.extend(("--datebefore", date_before))
    for match_filter in match_filters:
        command.extend(("--match-filters", match_filter))
    if playlist_items:
        command.extend(("--playlist-items", playlist_items))
    command.append(source_url)
    return command


_YOUTUBE_ERROR_RE = re.compile(r"ERROR:\s*\[youtube\]\s+([A-Za-z0-9_-]{6,})\s*:\s*(.*)", re.IGNORECASE)


def _classify_youtube_error(message: str) -> str:
    lowered = message.casefold()
    if "members-only" in lowered or "members only" in lowered or "join this channel" in lowered:
        return "members-only"
    if "private video" in lowered or "this video is private" in lowered:
        return "private"
    if "deleted" in lowered or "removed" in lowered:
        return "deleted"
    if "age-restricted" in lowered or "age restricted" in lowered:
        return "age-restricted"
    if "sign in" in lowered or "login" in lowered:
        return "authentication-required"
    if "unavailable" in lowered:
        return "unavailable"
    return "other-youtube-error"


def load_metadata(
    command: list[str],
    *,
    progress: ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], AcquisitionStats]:
    """Run yt-dlp, collecting JSON records and live acquisition telemetry.

    yt-dlp stdout is reserved for one JSON object per successfully extracted entry. stderr is
    relayed to the caller's stderr unchanged while also being inspected for uniquely identifiable
    YouTube extraction failures. Reading stderr on a dedicated thread prevents either pipe from
    blocking when the other stream is busy.
    """
    ensure_ytdlp()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YtDlpError(f"could not run yt-dlp: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    records: list[dict[str, Any]] = []
    stats = AcquisitionStats()

    def read_stderr() -> None:
        for raw_line in process.stderr:
            sys.stderr.write(raw_line)
            sys.stderr.flush()
            line = raw_line.rstrip("\n")
            if line.startswith("ERROR:"):
                stats.error_lines += 1
            match = _YOUTUBE_ERROR_RE.search(line)
            if match:
                stats.identified_error_lines += 1
                video_id, message = match.groups()
                category = _classify_youtube_error(message)
                if stats.record_skip(video_id, category) and progress is not None:
                    progress("skipped", stats, f"{video_id} ({category})")
            if progress is not None:
                progress("stderr", stats, line)

    stderr_thread = threading.Thread(target=read_stderr, name="yt-discover-ytdlp-stderr", daemon=True)
    stderr_thread.start()

    try:
        for line_number, line in enumerate(process.stdout, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                process.kill()
                process.wait()
                stderr_thread.join(timeout=1)
                raise YtDlpError(f"yt-dlp emitted invalid JSON on output line {line_number}: {exc.msg}") from exc
            if isinstance(value, dict):
                records.append(value)
                stats.available += 1
                if progress is not None:
                    detail = str(value.get("id") or value.get("webpage_url") or f"entry {stats.available}")
                    progress("available", stats, detail)
    finally:
        return_code = process.wait()
        stderr_thread.join()

    if return_code != 0 and not records:
        # yt-dlp may return a non-zero status even with --ignore-errors when every
        # requested video is inaccessible. If every reported ERROR line was tied
        # to an identifiable YouTube video, those failures have already been
        # recorded as per-entry skips and are safe for the caller to continue past.
        # Any unexplained process failure remains fatal so configuration, network,
        # invocation, or extractor-wide errors cannot be silently swallowed.
        fully_accounted_for = stats.identified_error_lines > 0 and stats.error_lines == stats.identified_error_lines
        if not fully_accounted_for:
            raise YtDlpError(f"yt-dlp exited with status {return_code}")
    return records, stats


@dataclass
class EnumerationStats:
    """Telemetry from a lightweight lazy channel enumeration pass."""

    enumerated: int = 0
    dated: int = 0
    undated: int = 0
    boundary_old_entries: int = 0
    frontier_overlap_entries: int = 0
    stopped_early: bool = False
    stopped_on_frontier: bool = False


def build_lazy_flat_command(
    source_url: str,
    *,
    cookies_file: Path = DEFAULT_COOKIES_FILE,
    extractor_args: str = DEFAULT_EXTRACTOR_ARGS,
    playlist_items: str | None = None,
) -> list[str]:
    """Build a lazy flat-playlist command for incremental channel enumeration."""
    command = [
        "yt-dlp",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--flat-playlist",
        "--lazy-playlist",
        "--dump-json",
    ]
    if cookies_file.is_file():
        command.extend(("--cookies", str(cookies_file)))
    combined_args = extractor_args.strip()
    approximate = "youtubetab:approximate_date"
    if combined_args:
        combined_args = f"{combined_args};{approximate}"
    else:
        combined_args = approximate
    command.extend(("--extractor-args", combined_args))
    if playlist_items:
        command.extend(("--playlist-items", playlist_items))
    command.append(source_url)
    return command


def build_video_metadata_command(
    video_ids: list[str],
    *,
    cookies_file: Path = DEFAULT_COOKIES_FILE,
    extractor_args: str = DEFAULT_EXTRACTOR_ARGS,
) -> list[str]:
    """Build one yt-dlp command that fully extracts a known set of YouTube video IDs."""
    command = [
        "yt-dlp",
        "--skip-download",
        "--ignore-errors",
        "--no-warnings",
        "--no-playlist",
        "--dump-json",
    ]
    if cookies_file.is_file():
        command.extend(("--cookies", str(cookies_file)))
    if extractor_args:
        command.extend(("--extractor-args", extractor_args))
    command.extend(f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids)
    return command


def enumerate_until_date_boundary(
    command: list[str],
    *,
    stop_before,
    confirmation_entries: int,
    progress: ProgressCallback | None = None,
) -> tuple[list[dict[str, Any]], EnumerationStats]:
    """Enumerate flat entries lazily and terminate yt-dlp once a safe old-date boundary is crossed.

    ``stop_before`` is deliberately earlier than the real query lower bound. yt-dlp's channel
    timestamps in flat mode are approximate, so callers should provide an appropriate safety
    margin. Several consecutive old dated entries are required before the process is terminated.
    """
    from datetime import date, datetime, timezone

    ensure_ytdlp()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YtDlpError(f"could not run yt-dlp: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    entries: list[dict[str, Any]] = []
    stats = EnumerationStats()

    def read_stderr() -> None:
        for raw_line in process.stderr:
            sys.stderr.write(raw_line)
            sys.stderr.flush()

    stderr_thread = threading.Thread(target=read_stderr, name="yt-discover-ytdlp-flat-stderr", daemon=True)
    stderr_thread.start()

    consecutive_old = 0
    terminated = False
    try:
        for line_number, line in enumerate(process.stdout, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                process.kill()
                process.wait()
                stderr_thread.join(timeout=1)
                raise YtDlpError(f"yt-dlp emitted invalid flat JSON on output line {line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                continue
            entries.append(value)
            stats.enumerated += 1
            timestamp = value.get("timestamp")
            approximate_date = None
            if isinstance(timestamp, (int, float)):
                try:
                    approximate_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
                except (OverflowError, OSError, ValueError):
                    approximate_date = None
            if approximate_date is None:
                upload_date = value.get("upload_date")
                if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
                    try:
                        approximate_date = date.fromisoformat(f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}")
                    except ValueError:
                        approximate_date = None

            if approximate_date is None:
                stats.undated += 1
                consecutive_old = 0
            else:
                stats.dated += 1
                if approximate_date < stop_before:
                    consecutive_old += 1
                    stats.boundary_old_entries += 1
                else:
                    consecutive_old = 0

            if progress is not None:
                detail = str(value.get("id") or f"entry {stats.enumerated}")
                progress("enumerated", AcquisitionStats(available=stats.enumerated), detail)

            if consecutive_old >= confirmation_entries:
                stats.stopped_early = True
                terminated = True
                process.terminate()
                break
    finally:
        if terminated:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        else:
            process.wait()
        stderr_thread.join()

    return entries, stats


def enumerate_all_flat(
    command: list[str],
) -> tuple[list[dict[str, Any]], EnumerationStats]:
    """Enumerate an entire flat source while preserving lightweight source order."""
    from datetime import datetime, timezone

    # Reuse the bounded enumerator with an unreachable historical boundary.  This
    # keeps stderr relay, parsing, and telemetry identical while naturally running
    # to the end of the source.
    return enumerate_until_date_boundary(
        command,
        stop_before=datetime(1970, 1, 1, tzinfo=timezone.utc).date(),
        confirmation_entries=3,
        progress=None,
    )


def enumerate_until_known_overlap(
    command: list[str],
    *,
    known_ids: set[str],
    confirmation_entries: int,
) -> tuple[list[dict[str, Any]], EnumerationStats]:
    """Enumerate newest-first flat entries until a conservative known-ID overlap is confirmed.

    The caller supplies IDs from a previously complete persisted source ordering. Several
    consecutive known IDs are required before stopping. If that overlap is never reached,
    enumeration naturally runs to the source end, allowing the caller to rebuild the frontier.
    """
    ensure_ytdlp()
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except OSError as exc:
        raise YtDlpError(f"could not run yt-dlp: {exc}") from exc

    assert process.stdout is not None
    assert process.stderr is not None
    entries: list[dict[str, Any]] = []
    stats = EnumerationStats()

    def read_stderr() -> None:
        for raw_line in process.stderr:
            sys.stderr.write(raw_line)
            sys.stderr.flush()

    stderr_thread = threading.Thread(target=read_stderr, name="yt-discover-ytdlp-frontier-stderr", daemon=True)
    stderr_thread.start()
    consecutive_known = 0
    try:
        for line_number, line in enumerate(process.stdout, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                process.kill()
                process.wait()
                stderr_thread.join(timeout=1)
                raise YtDlpError(f"yt-dlp emitted invalid flat JSON on output line {line_number}: {exc.msg}") from exc
            if not isinstance(value, dict):
                continue
            entries.append(value)
            stats.enumerated += 1
            video_id = value.get("id")
            if isinstance(video_id, str) and video_id in known_ids:
                consecutive_known += 1
                stats.frontier_overlap_entries += 1
            else:
                consecutive_known = 0
            if consecutive_known >= confirmation_entries:
                stats.stopped_early = True
                stats.stopped_on_frontier = True
                process.terminate()
                break
    finally:
        return_code = process.wait() if process.poll() is None else process.returncode
        stderr_thread.join()

    if return_code not in (0, -15) and not stats.stopped_on_frontier:
        raise YtDlpError(f"yt-dlp flat enumeration exited with status {return_code}")
    return entries, stats
