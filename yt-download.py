#!/usr/bin/env python3
"""Download media through yt-dlp using a small, predictable wrapper.

The downloader resolves typed operational policy from built-in defaults, optional
parameter profiles and explicit CLI settings while delegating output location
and naming to optional output profiles stored beside the script in ``profiles``.

Targets may be supplied directly on the command line, read from standard input,
read from an explicitly named batch file, or read from ``./ids.txt`` when no
input is specified.

Downloader configuration has two deliberately separate profile layers:

* ``-p NAME`` selects a named parameter profile from ``defaults.json``.
* ``-P NAME`` selects an output-layout profile from ``profiles/``.
* Explicit CLI options override values loaded from a parameter profile.
* Output profiles remain the existing UTF-8 ``@profile`` files containing
  ``path`` and/or ``output`` settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROGRAM_NAME = "yt-download.py"
PROGRAM_VERSION = "1.19.0"

SCRIPT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = SCRIPT_DIR / "profiles"
DEFAULT_PROFILE_NAME = "default"
PROFILE_SIGNATURE = "@profile"
DEFAULTS_FILE = SCRIPT_DIR / "defaults.json"
PARAMETER_PROFILE_VERSION = 1
RUN_MANIFEST_SCHEMA_VERSION = 1
MACHINE_CONTRACT_VERSION = 1
PLAN_SCHEMA_VERSION = 1
CAPABILITIES_SCHEMA_VERSION = 1
CONFIG_VALIDATION_SCHEMA_VERSION = 1
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
PARAMETER_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUPPORTED_COOKIE_BROWSERS = frozenset(
    {"brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"}
)

PARAMETER_PROFILE_KEYS = (
    "resolution",
    "format",
    "cookies",
    "cookies-from-browser",
    "no-cookies",
    "reverse-playlist",
    "playlist",
    "playlist-items",
    "live",
    "live-from-start",
    "wait-for-video",
    "write-live-chat",
    "chapter-sections",
    "time-ranges",
    "limit-rate",
    "throttled-rate",
    "concurrent-fragments",
    "retries",
    "fragment-retries",
    "file-access-retries",
    "extractor-retries",
    "retry-sleep",
    "archive",
    "temp-path",
    "extractor-args",
    "min-resolution",
    "max-resolution",
    "min-fps",
    "max-fps",
    "preferred-fps",
    "preferred-video-codec",
    "preferred-audio-codec",
    "preferred-hdr",
    "preferred-audio-channels",
    "merge-container",
    "audio-only",
    "audio-source-codec",
    "audio-source-container",
    "audio-source-fallback",
    "audio-format",
    "audio-quality",
    "write-subs",
    "write-auto-subs",
    "sub-langs",
    "sub-format",
    "embed-subs",
    "write-thumbnail",
    "embed-thumbnail",
    "write-info-json",
    "embed-metadata",
    "embed-chapters",
    "sponsorblock",
    "sponsorblock-mark",
    "sponsorblock-remove",
)

DEFAULT_VIDEO_ID_FILE = Path("./ids.txt")
ARCHIVE_FILE = SCRIPT_DIR / "archive.txt"
COOKIES_FILE = SCRIPT_DIR / "cookies.txt"
TEMP_DIR = Path("/mnt/storage/Temp/yt-dlp")

DEFAULT_RESOLUTION = "1440"
DEFAULT_DOWNLOAD_RATE = "20M"
FORMAT_SELECTOR = "bv+ba/best"
DEFAULT_EXTRACTOR_ARGS = ("youtube:player-client=default,-android_sdkless",)
SUPPORTED_MERGE_CONTAINERS = frozenset({"avi", "flv", "mkv", "mov", "mp4", "webm"})
SUPPORTED_AUDIO_FORMATS = frozenset({"best", "aac", "alac", "flac", "m4a", "mp3", "opus", "vorbis", "wav"})
SPONSORBLOCK_MARK_CATEGORIES = frozenset(
    {
        "sponsor",
        "intro",
        "outro",
        "selfpromo",
        "preview",
        "filler",
        "interaction",
        "music_offtopic",
        "hook",
        "poi_highlight",
        "chapter",
        "all",
        "default",
    }
)
SPONSORBLOCK_REMOVE_CATEGORIES = SPONSORBLOCK_MARK_CATEGORIES - {"poi_highlight", "chapter"}
DEFAULT_SPONSORBLOCK_REMOVE = "all"


# Machine-facing schema metadata is kept explicit rather than inferred from argparse.
# The CLI and profile format have related but intentionally different contracts.
PARAMETER_SETTING_DESCRIPTIONS = {
    "resolution": "Preferred vertical resolution used for format sorting.",
    "format": "Expert yt-dlp format selector. This is passed through unchanged.",
    "cookies": "Path to a Netscape-format cookie file.",
    "cookies-from-browser": "yt-dlp browser-cookie specification.",
    "no-cookies": "Disable both explicit and automatic cookie discovery.",
    "reverse-playlist": "Traverse a playlist in reverse order.",
    "playlist": "Allow or suppress playlist traversal.",
    "playlist-items": "Ordered yt-dlp playlist item selections after Downloader validation.",
    "live": "Enable explicit live-media workflow semantics.",
    "live-from-start": "Request supported acquisition from the beginning of a live stream.",
    "wait-for-video": "Wait interval for a scheduled live stream, as MIN or MIN-MAX seconds.",
    "write-live-chat": "Request live chat as an associated subtitle sidecar when available.",
    "chapter-sections": "Regular expressions selecting chapter-derived partial-media outputs.",
    "time-ranges": "Partial-media time ranges, each represented as START-STOP or [START, STOP].",
    "limit-rate": "Maximum download rate accepted by yt-dlp.",
    "throttled-rate": "Rate below which yt-dlp may consider the download throttled.",
    "concurrent-fragments": "Number of fragments downloaded concurrently per stream.",
    "retries": "Whole-download retry count or the literal infinite.",
    "fragment-retries": "Fragment retry count or the literal infinite.",
    "file-access-retries": "File-access retry count or the literal infinite.",
    "extractor-retries": "Extractor retry count or the literal infinite.",
    "retry-sleep": "Ordered yt-dlp retry-sleep expressions.",
    "archive": "Path to the yt-dlp download archive used for whole-item completion.",
    "temp-path": "Temporary path used for yt-dlp intermediate output.",
    "extractor-args": "Ordered, explicitly supplied yt-dlp extractor-argument expressions.",
    "min-resolution": "Minimum required video height in pixels.",
    "max-resolution": "Maximum required video height in pixels.",
    "min-fps": "Minimum required frame rate.",
    "max-fps": "Maximum required frame rate.",
    "preferred-fps": "Preferred frame rate used for format sorting.",
    "preferred-video-codec": "Preferred video codec used for fallback-friendly format sorting.",
    "preferred-audio-codec": "Preferred audio codec used for fallback-friendly format sorting.",
    "preferred-hdr": "Preferred dynamic-range class used for format sorting.",
    "preferred-audio-channels": "Preferred audio channel count used for format sorting.",
    "merge-container": "Container requested when yt-dlp merges separate streams.",
    "audio-only": "Select an existing audio-only source stream without enabling conversion.",
    "audio-source-codec": "Require this source audio codec before optional conversion.",
    "audio-source-container": "Require this source audio container/extension before optional conversion.",
    "audio-source-fallback": "Allow fallback to another audio source when exact source constraints do not match.",
    "audio-format": "Explicitly enable audio extraction/conversion to this format.",
    "audio-quality": "Audio conversion quality accepted by yt-dlp/FFmpeg.",
    "write-subs": "Write manually supplied subtitles when available.",
    "write-auto-subs": "Write automatically generated subtitles when available.",
    "sub-langs": "yt-dlp subtitle-language selection expression.",
    "sub-format": "yt-dlp subtitle-format preference expression.",
    "embed-subs": "Embed requested subtitles into the primary output when supported.",
    "write-thumbnail": "Write an associated thumbnail when available.",
    "embed-thumbnail": "Embed a requested thumbnail when supported.",
    "write-info-json": "Write yt-dlp information JSON as an associated artefact.",
    "embed-metadata": "Embed media metadata into the primary output when supported.",
    "embed-chapters": "Embed chapter metadata into the primary output when supported.",
    "sponsorblock": "Enable Downloader SponsorBlock policy.",
    "sponsorblock-mark": "SponsorBlock categories to mark as chapters.",
    "sponsorblock-remove": "SponsorBlock categories to remove from the media.",
}
HARD_FORMAT_CONSTRAINT_KEYS = frozenset(
    {
        "min-resolution",
        "max-resolution",
        "min-fps",
        "max-fps",
    }
)

EXAMPLES = r"""Examples:

  Use the backwards-compatible default input file, ./ids.txt:
    %(prog)s

  Download one target directly:
    %(prog)s dQw4w9WgXcQ

  Download several direct targets:
    %(prog)s VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3

  Read targets from a named batch file:
    %(prog)s ids.txt
    %(prog)s --input-file /path/to/ids.txt

  Read newline-separated targets from standard input:
    printf '%%s\n' VIDEO_ID_1 VIDEO_ID_2 | %(prog)s -

  Pipe discovery output directly into the downloader:
    yt-discover @SomeChannel --after 2025-01-01 | %(prog)s -

  Select a named parameter profile from defaults.json:
    %(prog)s -p 4k VIDEO_ID
    %(prog)s -p playlist PLAYLIST_URL

  List available parameter profiles:
    %(prog)s --list-parameters

  Select an output-layout profile by name or path:
    %(prog)s -P playlist PLAYLIST_URL
    %(prog)s --output-profile /srv/youtube/profiles/music VIDEO_ID

  Prefer 1080p when yt-dlp sorts available formats:
    %(prog)s -r 1080 VIDEO_ID

  Supply yt-dlp's format selector directly:
    %(prog)s -f "bv*[height<=1080]+ba/b" VIDEO_ID

  Apply typed format constraints and preferences:
    %(prog)s --min-resolution 1080 --max-resolution 2160 --preferred-video-codec av01 VIDEO_ID
    %(prog)s --max-fps 60 --preferred-fps 60 --preferred-hdr hdr --merge-container mkv VIDEO_ID

  Select an existing audio-only source without transcoding:
    %(prog)s --audio-only VIDEO_ID
    %(prog)s --audio-only --audio-source-codec opus --audio-source-container webm VIDEO_ID

  Explicitly allow audio conversion when a converted output is wanted:
    %(prog)s --audio-format flac VIDEO_ID
    %(prog)s --audio-format mp3 --audio-quality 192K VIDEO_ID

  Select and embed subtitles while retaining a sidecar copy:
    %(prog)s --write-subs --sub-langs "en.*,cy" --sub-format "srt/best" --embed-subs VIDEO_ID

  Write metadata sidecars and control embedded metadata/chapters:
    %(prog)s --write-info-json --write-thumbnail VIDEO_ID
    %(prog)s --no-embed-metadata --no-embed-chapters VIDEO_ID

  Mark or remove specific SponsorBlock categories, or disable SponsorBlock entirely:
    %(prog)s --sponsorblock-mark sponsor,intro --sponsorblock-remove selfpromo VIDEO_ID
    %(prog)s --no-sponsorblock VIDEO_ID

  Reverse playlist traversal:
    %(prog)s --rev PLAYLIST_URL

  Select playlist entries by index, inclusive range or slice:
    %(prog)s --playlist-index 3 PLAYLIST_URL
    %(prog)s --playlist-range 5 12 PLAYLIST_URL
    %(prog)s --playlist-slice 1:20:2 PLAYLIST_URL
    %(prog)s --playlist-index 1 --playlist-range 5 8 --playlist-slice=-5: PLAYLIST_URL

  Combine parameter-profile selection, an explicit override and playlist reversal:
    %(prog)s -p playlist -r 1440 --rev PLAYLIST_URL

  Acquire an active live stream from the current edge or, where supported, from its beginning:
    %(prog)s --live LIVE_URL
    %(prog)s --live --live-from-start LIVE_URL

  Wait for a scheduled stream and optionally request its live-chat sidecar:
    %(prog)s --live --wait-for-video 60-300 SCHEDULED_URL
    %(prog)s --live --write-live-chat LIVE_URL

  Download derivative portions by chapter match or time range:
    %(prog)s --chapter-section "^Introduction$" VIDEO_ID
    %(prog)s --time-range 1:30 3:00 VIDEO_ID
    %(prog)s --time-range -60 inf VIDEO_ID

  Restore whole-item acquisition when a profile selects partial media:
    %(prog)s -p excerpt --whole-item VIDEO_ID

  Remove IDs from a batch file immediately after each video is fully processed:
    %(prog)s --remove-completed-ids ids/batch.txt
    %(prog)s --remove-completed-ids --input-file ids/batch.txt

  A failed, skipped, interrupted or partially processed video remains in the file.
  The removal callback runs at yt-dlp's after_move stage, after successful post-processing.

  Limit rate, increase fragment concurrency and adjust retries:
    %(prog)s --limit-rate 12M -N 4 --retries infinite VIDEO_ID
    %(prog)s --fragment-retries 20 --retry-sleep fragment:exp=1:20 VIDEO_ID

  Override the archive and temporary paths:
    %(prog)s --archive ~/media/archive.txt --temp-path ~/media/tmp VIDEO_ID

  Use an explicit cookies file when authentication is required:
    %(prog)s --cookies /path/to/cookies.txt VIDEO_ID

  Load cookies directly from a browser:
    %(prog)s --cookies-from-browser firefox VIDEO_ID

  Ignore an automatically discovered script-local cookies.txt:
    %(prog)s --no-cookies VIDEO_ID

  Explain the resolved download plan without executing it:
    %(prog)s --explain -p playlist PLAYLIST_URL

  Emit the versioned machine contract and parameter-profile schema:
    %(prog)s --schema-json

  Validate the resolved defaults file without downloading:
    %(prog)s --validate-config

  Report machine-readable local capabilities:
    %(prog)s --capabilities-json

  Emit the versioned resolved plan without executing it:
    %(prog)s --explain-json -p playlist PLAYLIST_URL

  Print the resolved yt-dlp command without executing it:
    %(prog)s --dry-run -p playlist PLAYLIST_URL

  Write a redacted run manifest after actual execution:
    %(prog)s --run-manifest run.json VIDEO_ID

  Include SHA-256 hashes for successfully completed primary outputs:
    %(prog)s --run-manifest run.json --hash-outputs VIDEO_ID

  Emit a new parameter profile without modifying defaults.json:
    %(prog)s --resolution 1440p --format "bv+ba/best" --no-cookies --generate-profile offline-1440

  Add that generated profile directly to a defaults file:
    %(prog)s -d defaults.json --resolution 1440p --no-cookies --generate-profile offline-1440 --write-profile

Parameter profiles are versioned JSON objects in defaults.json. Explicit CLI settings override selected profile values.

Output-profile format:

  @profile
  path=/mnt/storage/Downloads/YouTube/
  output=%%(title)s [%%(id)s] [%%(uploader)s].%%(ext)s

Profile resolution:

  requested profile -> profiles/default -> yt-dlp native output defaults

An existing but invalid profile is an error. A missing profile is recoverable.
"""


@dataclass(frozen=True)
class OutputProfile:
    """Output location and yt-dlp output-template settings for one profile."""

    source: Path
    path: str | None = None
    output: str | None = None


@dataclass(frozen=True)
class DownloadPolicy:
    """Resolved global yt-dlp policy for one invocation."""

    resolution: str
    format_selector: str
    reverse_playlist: bool
    playlist: bool | None = None
    playlist_items: tuple[str, ...] = ()
    live: bool = False
    live_from_start: bool = False
    wait_for_video: str | None = None
    write_live_chat: bool = False
    chapter_sections: tuple[str, ...] = ()
    time_ranges: tuple[str, ...] = ()
    limit_rate: str = DEFAULT_DOWNLOAD_RATE
    throttled_rate: str | None = None
    concurrent_fragments: int | None = None
    retries: str | None = None
    fragment_retries: str | None = None
    file_access_retries: str | None = None
    extractor_retries: str | None = None
    retry_sleep: tuple[str, ...] = ()
    archive_file: Path = ARCHIVE_FILE
    temp_path: Path = TEMP_DIR
    extractor_args: tuple[str, ...] = DEFAULT_EXTRACTOR_ARGS
    min_resolution: int | None = None
    max_resolution: int | None = None
    min_fps: int | None = None
    max_fps: int | None = None
    preferred_fps: int | None = None
    preferred_video_codec: str | None = None
    preferred_audio_codec: str | None = None
    preferred_hdr: str | None = None
    preferred_audio_channels: int | None = None
    merge_container: str | None = None
    audio_only: bool = False
    audio_source_codec: str | None = None
    audio_source_container: str | None = None
    audio_source_fallback: bool = True
    audio_format: str | None = None
    audio_quality: str | None = None
    write_subtitles: bool = False
    write_auto_subtitles: bool = False
    subtitle_languages: str | None = None
    subtitle_format: str | None = None
    embed_subtitles: bool = False
    write_thumbnail: bool = False
    embed_thumbnail: bool = False
    write_info_json: bool = False
    embed_metadata: bool = True
    embed_chapters: bool = True
    sponsorblock: bool = True
    sponsorblock_mark: str | None = None
    sponsorblock_remove: str | None = DEFAULT_SPONSORBLOCK_REMOVE

    @property
    def playlist_item_spec(self) -> str | None:
        """Return the canonical yt-dlp playlist item specification, if constrained."""
        return ",".join(self.playlist_items) if self.playlist_items else None

    @property
    def partial_media(self) -> bool:
        """Return whether this invocation produces derivative partial-media outputs."""
        return bool(self.chapter_sections or self.time_ranges)

    @property
    def download_sections(self) -> tuple[str, ...]:
        """Return canonical yt-dlp download-section expressions in policy order."""
        return self.chapter_sections + tuple(f"*{value}" for value in self.time_ranges)

    @property
    def effective_format_selector(self) -> str:
        """Return the raw or generated yt-dlp selector for this policy."""
        if self.audio_only or self.audio_format is not None:
            filters: list[str] = []
            if self.audio_source_codec is not None:
                filters.append(f"[acodec={self.audio_source_codec}]")
            if self.audio_source_container is not None:
                filters.append(f"[ext={self.audio_source_container}]")
            selector = f"ba{''.join(filters)}"
            if filters and self.audio_source_fallback:
                selector += "/ba"
            return selector

        filters: list[str] = []
        if self.min_resolution is not None:
            filters.append(f"[height>={self.min_resolution}]")
        if self.max_resolution is not None:
            filters.append(f"[height<={self.max_resolution}]")
        if self.min_fps is not None:
            filters.append(f"[fps>={self.min_fps}]")
        if self.max_fps is not None:
            filters.append(f"[fps<={self.max_fps}]")
        if not filters:
            return self.format_selector
        suffix = "".join(filters)
        return f"bv{suffix}+ba/b{suffix}"

    @property
    def sort_selector(self) -> str:
        """Return yt-dlp's format sort expression for resolved preferences."""
        fields: list[str] = []
        if self.audio_only or self.audio_format is not None:
            if self.preferred_audio_codec is not None:
                fields.append(f"acodec:{self.preferred_audio_codec}")
            if self.preferred_audio_channels is not None:
                fields.append(f"channels:{self.preferred_audio_channels}")
            fields.extend(("lang", "br", "size"))
            return ",".join(fields)

        if self.preferred_video_codec is not None:
            fields.append(f"vcodec:{self.preferred_video_codec}")
        if self.preferred_audio_codec is not None:
            fields.append(f"acodec:{self.preferred_audio_codec}")
        if self.preferred_audio_channels is not None:
            fields.append(f"channels:{self.preferred_audio_channels}")
        if self.preferred_fps is not None:
            fields.append(f"fps:{self.preferred_fps}")
        if self.preferred_hdr == "sdr":
            fields.append("+hdr")
        elif self.preferred_hdr == "hdr":
            fields.append("hdr:12")
        elif self.preferred_hdr == "dv":
            fields.append("hdr")
        if self.resolution == "best":
            fields.extend(("res", "lang", "fps", "size"))
        else:
            fields.extend((f"res:{self.resolution}", "lang", "fps", "size"))
        return ",".join(fields)


@dataclass(frozen=True)
class ParameterProfile:
    """One validated named Downloader parameter profile."""

    name: str
    settings: dict[str, object]
    source: Path


@dataclass(frozen=True)
class ResolvedParameterSettings:
    """Merged Downloader settings plus the source of each effective value."""

    settings: dict[str, object]
    sources: dict[str, str]


@dataclass(frozen=True)
class InputSource:
    """Describe how yt-dlp should receive download targets."""

    batch_file: Path | None = None
    stdin: bool = False
    direct_targets: tuple[str, ...] = ()

    def append_to(self, command: list[str]) -> None:
        """Append the input arguments represented by this source to a command."""
        if self.batch_file is not None:
            command.extend(("--batch-file", str(self.batch_file)))
        elif self.stdin:
            command.extend(("--batch-file", "-"))
        else:
            command.extend(self.direct_targets)


@dataclass(frozen=True)
class DownloadPlan:
    """Fully resolved Downloader plan ready for explanation or execution."""

    executable: str
    policy: DownloadPolicy
    input_source: InputSource
    output_profile: OutputProfile | None
    cookies_file: Path | None
    cookies_from_browser: str | None
    cookies_source: str
    remove_completed_ids: bool
    defaults_file: Path
    parameter_profile: ParameterProfile | None
    parameter_sources: dict[str, str]

    def command(self, *, output_event_file: Path | None = None) -> list[str]:
        """Return the exact yt-dlp command represented by this plan."""
        return build_yt_dlp_command(
            self.executable,
            self.policy,
            self.input_source,
            self.output_profile,
            cookies_file=self.cookies_file,
            cookies_from_browser=self.cookies_from_browser,
            remove_completed_ids=self.remove_completed_ids,
            output_event_file=output_event_file,
        )


def _append_playlist_cli_item(namespace: argparse.Namespace, expression: str) -> None:
    """Append one canonical playlist selector while preserving CLI option order."""
    current = list(getattr(namespace, "playlist_items", None) or ())
    current.append(expression)
    namespace.playlist_items = current


class PlaylistIndexAction(argparse.Action):
    """Argparse action for one validated playlist index."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        try:
            value = _validate_playlist_index(values)
        except ValueError as exc:
            raise argparse.ArgumentError(self, str(exc)) from exc
        _append_playlist_cli_item(namespace, str(value))


class PlaylistRangeAction(argparse.Action):
    """Argparse action for one inclusive playlist range."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        start, stop = values
        try:
            start = _validate_playlist_index(start, label="playlist range START")
            stop = _validate_playlist_index(stop, label="playlist range STOP")
        except ValueError as exc:
            raise argparse.ArgumentError(self, str(exc)) from exc
        _append_playlist_cli_item(namespace, f"{start}:{stop}")


class PlaylistSliceAction(argparse.Action):
    """Argparse action for one validated playlist slice."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        try:
            expression = _normalise_playlist_slice(values)
        except ValueError as exc:
            raise argparse.ArgumentError(self, str(exc)) from exc
        _append_playlist_cli_item(namespace, expression)


def build_parser() -> argparse.ArgumentParser:
    """Construct and return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Download targets with the project's standard yt-dlp settings. "
            "With no targets, ./ids.txt is used for backwards compatibility."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Output profiles live in the profiles/ directory beside this script.\n"
            "Run %(prog)s --examples for practical examples and profile syntax."
        ),
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="TARGET",
        help=("Video ID, URL, local batch file, or '-' for standard input. Multiple direct targets may be supplied."),
    )
    parser.add_argument(
        "-p",
        "--parameter-profile",
        metavar="NAME",
        help="Apply named download parameters from the resolved defaults JSON file.",
    )
    parser.add_argument(
        "-d",
        "--defaults",
        type=Path,
        metavar="FILE",
        help="Use FILE for named parameter profiles instead of script-local defaults.json.",
    )
    parser.add_argument(
        "--list-parameters",
        action="store_true",
        help="List named parameter profiles in the resolved defaults JSON file and exit.",
    )
    parser.add_argument(
        "--schema-json",
        action="store_true",
        help="Emit the versioned Downloader machine contract and parameter-profile JSON Schema, then exit.",
    )
    parser.add_argument(
        "--validate-config",
        nargs="?",
        const="",
        metavar="FILE",
        help="Validate FILE, or the resolved defaults JSON when FILE is omitted, then exit.",
    )
    parser.add_argument(
        "--capabilities",
        action="store_true",
        help="Report Downloader and external-tool capabilities, then exit.",
    )
    parser.add_argument(
        "--capabilities-json",
        action="store_true",
        help="Report Downloader and external-tool capabilities as versioned JSON, then exit.",
    )
    parser.add_argument(
        "--generate-profile",
        metavar="NAME",
        help="Generate a named parameter profile from profile-eligible settings and exit.",
    )
    parser.add_argument(
        "--write-profile",
        action="store_true",
        help="Write --generate-profile into the resolved defaults JSON file instead of only printing it.",
    )
    parser.add_argument(
        "--overwrite-profile",
        action="store_true",
        help="Allow --write-profile to replace an existing profile of the same name.",
    )
    parser.add_argument(
        "-P",
        "--output-profile",
        "--profile",
        dest="output_profile",
        metavar="PROFILE",
        help=(
            "Output-layout profile name or explicit path. --profile is retained as a legacy alias; "
            "bare names are looked up under profiles/ beside this script."
        ),
    )
    parser.add_argument(
        "-r",
        "--resolution",
        default=None,
        metavar="RESOLUTION",
        help=(
            f"Preferred vertical resolution used for format sorting (built-in default: {DEFAULT_RESOLUTION}). "
            "Accepts a positive number, an optional 'p' suffix, or 'best'."
        ),
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format_selector",
        default=None,
        metavar="FORMAT",
        help=(
            f"Pass yt-dlp format selector FORMAT directly (built-in default: {FORMAT_SELECTOR}). "
            "This may also be stored in a parameter profile."
        ),
    )
    parser.add_argument(
        "--min-resolution",
        metavar="RESOLUTION",
        help="Require video height of at least RESOLUTION pixels.",
    )
    parser.add_argument(
        "--max-resolution",
        metavar="RESOLUTION",
        help="Require video height of at most RESOLUTION pixels.",
    )
    parser.add_argument("--min-fps", type=int, metavar="FPS", help="Require a frame rate of at least FPS.")
    parser.add_argument("--max-fps", type=int, metavar="FPS", help="Require a frame rate of at most FPS.")
    parser.add_argument(
        "--preferred-fps", type=int, metavar="FPS", help="Prefer formats near FPS without making it a hard requirement."
    )
    parser.add_argument(
        "--preferred-video-codec",
        metavar="CODEC",
        help="Prefer yt-dlp video codec CODEC while allowing fallback formats.",
    )
    parser.add_argument(
        "--preferred-audio-codec",
        metavar="CODEC",
        help="Prefer yt-dlp audio codec CODEC while allowing fallback formats.",
    )
    parser.add_argument(
        "--preferred-hdr",
        choices=("sdr", "hdr", "dv"),
        help="Prefer SDR, HDR up to 12-bit, or Dolby Vision without requiring it.",
    )
    parser.add_argument(
        "--preferred-audio-channels",
        type=int,
        metavar="CHANNELS",
        help="Prefer formats near CHANNELS audio channels without requiring an exact match.",
    )
    parser.add_argument(
        "--merge-container",
        choices=tuple(sorted(SUPPORTED_MERGE_CONTAINERS)),
        metavar="CONTAINER",
        help=(
            "Choose the container used when yt-dlp must merge separate streams; does not force remuxing or transcoding."
        ),
    )
    audio_only_group = parser.add_mutually_exclusive_group()
    audio_only_group.add_argument(
        "--audio-only",
        dest="audio_only",
        action="store_true",
        default=None,
        help="Select an existing audio-only source stream without enabling audio conversion.",
    )
    audio_only_group.add_argument(
        "--no-audio-only",
        dest="audio_only",
        action="store_false",
        help="Disable audio-only source selection inherited from a parameter profile.",
    )
    parser.add_argument(
        "--audio-source-codec",
        metavar="CODEC",
        help="Require source audio codec CODEC before any explicitly requested conversion.",
    )
    parser.add_argument(
        "--audio-source-container",
        metavar="EXT",
        help="Require source audio container/extension EXT before any explicitly requested conversion.",
    )
    audio_fallback_group = parser.add_mutually_exclusive_group()
    audio_fallback_group.add_argument(
        "--audio-source-fallback",
        dest="audio_source_fallback",
        action="store_true",
        default=None,
        help="Allow fallback to another existing audio source when source codec/container constraints miss.",
    )
    audio_fallback_group.add_argument(
        "--no-audio-source-fallback",
        dest="audio_source_fallback",
        action="store_false",
        help="Require the requested source codec/container exactly instead of falling back.",
    )
    parser.add_argument(
        "--audio-format",
        choices=tuple(sorted(SUPPORTED_AUDIO_FORMATS)),
        metavar="FORMAT",
        help="Explicitly allow yt-dlp/FFmpeg audio extraction/conversion to FORMAT.",
    )
    parser.add_argument(
        "--audio-quality",
        metavar="QUALITY",
        help="Audio conversion quality: integer 0..10 for VBR or a bitrate such as 128K.",
    )
    subtitle_write_group = parser.add_mutually_exclusive_group()
    subtitle_write_group.add_argument(
        "--write-subs",
        dest="write_subs",
        action="store_true",
        default=None,
        help="Write manually provided subtitles as sidecar files.",
    )
    subtitle_write_group.add_argument(
        "--no-write-subs",
        dest="write_subs",
        action="store_false",
        help="Do not write manually provided subtitle sidecars.",
    )
    auto_subtitle_group = parser.add_mutually_exclusive_group()
    auto_subtitle_group.add_argument(
        "--write-auto-subs",
        dest="write_auto_subs",
        action="store_true",
        default=None,
        help="Write automatically generated subtitles when available.",
    )
    auto_subtitle_group.add_argument(
        "--no-write-auto-subs",
        dest="write_auto_subs",
        action="store_false",
        help="Do not write automatically generated subtitles.",
    )
    parser.add_argument(
        "--sub-langs",
        metavar="LANGS",
        help="Select subtitle languages using yt-dlp's comma-separated language/regex syntax.",
    )
    parser.add_argument(
        "--sub-format",
        metavar="FORMAT",
        help="Select subtitle formats using yt-dlp's preference syntax, such as 'srt/best'.",
    )
    embed_subtitle_group = parser.add_mutually_exclusive_group()
    embed_subtitle_group.add_argument(
        "--embed-subs",
        dest="embed_subs",
        action="store_true",
        default=None,
        help="Embed selected subtitles into supported output containers.",
    )
    embed_subtitle_group.add_argument(
        "--no-embed-subs",
        dest="embed_subs",
        action="store_false",
        help="Do not embed subtitles into the media file.",
    )
    thumbnail_write_group = parser.add_mutually_exclusive_group()
    thumbnail_write_group.add_argument(
        "--write-thumbnail",
        dest="write_thumbnail",
        action="store_true",
        default=None,
        help="Write the selected thumbnail as a sidecar file.",
    )
    thumbnail_write_group.add_argument(
        "--no-write-thumbnail",
        dest="write_thumbnail",
        action="store_false",
        help="Do not write a thumbnail sidecar.",
    )
    thumbnail_embed_group = parser.add_mutually_exclusive_group()
    thumbnail_embed_group.add_argument(
        "--embed-thumbnail",
        dest="embed_thumbnail",
        action="store_true",
        default=None,
        help="Embed the thumbnail as cover art when supported.",
    )
    thumbnail_embed_group.add_argument(
        "--no-embed-thumbnail",
        dest="embed_thumbnail",
        action="store_false",
        help="Do not embed a thumbnail.",
    )
    info_json_group = parser.add_mutually_exclusive_group()
    info_json_group.add_argument(
        "--write-info-json",
        dest="write_info_json",
        action="store_true",
        default=None,
        help="Write yt-dlp's media information JSON as a sidecar file.",
    )
    info_json_group.add_argument(
        "--no-write-info-json",
        dest="write_info_json",
        action="store_false",
        help="Do not write an information JSON sidecar.",
    )
    metadata_group = parser.add_mutually_exclusive_group()
    metadata_group.add_argument(
        "--embed-metadata",
        dest="embed_metadata",
        action="store_true",
        default=None,
        help="Embed metadata into the output media file (built-in default: enabled).",
    )
    metadata_group.add_argument(
        "--no-embed-metadata",
        dest="embed_metadata",
        action="store_false",
        help="Disable Downloader's built-in metadata embedding.",
    )
    chapter_group = parser.add_mutually_exclusive_group()
    chapter_group.add_argument(
        "--embed-chapters",
        dest="embed_chapters",
        action="store_true",
        default=None,
        help="Embed chapter markers into the output media file (built-in default: enabled).",
    )
    chapter_group.add_argument(
        "--no-embed-chapters",
        dest="embed_chapters",
        action="store_false",
        help="Disable Downloader's built-in chapter embedding.",
    )
    sponsorblock_group = parser.add_mutually_exclusive_group()
    sponsorblock_group.add_argument(
        "--sponsorblock",
        dest="sponsorblock",
        action="store_true",
        default=None,
        help="Enable SponsorBlock processing (built-in default: enabled with remove=all).",
    )
    sponsorblock_group.add_argument(
        "--no-sponsorblock",
        dest="sponsorblock",
        action="store_false",
        help="Disable SponsorBlock marking and removal.",
    )
    parser.add_argument(
        "--sponsorblock-mark",
        metavar="CATS",
        help="Create chapters for validated SponsorBlock categories.",
    )
    parser.add_argument(
        "--sponsorblock-remove",
        metavar="CATS",
        help="Remove validated SponsorBlock categories (built-in default: all).",
    )
    live_group = parser.add_mutually_exclusive_group()
    live_group.add_argument(
        "--live",
        dest="live",
        action="store_true",
        default=None,
        help="Enable explicit live-media acquisition policy for this invocation.",
    )
    live_group.add_argument(
        "--no-live",
        dest="live",
        action="store_false",
        help="Disable live-media policy inherited from a parameter profile.",
    )
    live_start_group = parser.add_mutually_exclusive_group()
    live_start_group.add_argument(
        "--live-from-start",
        dest="live_from_start",
        action="store_true",
        default=None,
        help="For supported live extractors, ask yt-dlp to acquire the stream from its beginning.",
    )
    live_start_group.add_argument(
        "--live-edge",
        "--no-live-from-start",
        dest="live_from_start",
        action="store_false",
        help="Acquire from the current live edge, overriding a live-from-start parameter profile.",
    )
    parser.add_argument(
        "--wait-for-video",
        metavar="MIN[-MAX]",
        help="Wait for a scheduled live target using a validated yt-dlp retry interval in seconds.",
    )
    parser.add_argument(
        "--no-wait-for-video",
        dest="no_wait_for_video",
        action="store_true",
        help="Disable scheduled-stream waiting inherited from a parameter profile.",
    )
    live_chat_group = parser.add_mutually_exclusive_group()
    live_chat_group.add_argument(
        "--write-live-chat",
        dest="write_live_chat",
        action="store_true",
        default=None,
        help="Request the live_chat subtitle stream as a sidecar when the extractor provides it.",
    )
    live_chat_group.add_argument(
        "--no-write-live-chat",
        dest="write_live_chat",
        action="store_false",
        help="Disable live-chat sidecar acquisition inherited from a parameter profile.",
    )
    parser.add_argument(
        "--chapter-section",
        dest="chapter_sections",
        action="append",
        metavar="REGEX",
        help=(
            "Download chapters matching REGEX as derivative section outputs. Repeat to add further chapter expressions."
        ),
    )
    parser.add_argument(
        "--time-range",
        dest="time_ranges",
        action="append",
        nargs=2,
        metavar=("START", "STOP"),
        help=(
            "Download derivative media from START to STOP. Timestamps accept seconds or "
            "colon-separated clock values; STOP may be 'inf'. Repeat for further ranges."
        ),
    )
    parser.add_argument(
        "--whole-item",
        action="store_true",
        help="Disable chapter/time-range selection inherited from a parameter profile.",
    )
    parser.add_argument(
        "--limit-rate",
        metavar="RATE",
        help=f"Limit download rate using yt-dlp RATE syntax (built-in default: {DEFAULT_DOWNLOAD_RATE}).",
    )
    parser.add_argument(
        "--throttled-rate",
        metavar="RATE",
        help="Treat transfer rates below RATE as throttled and allow yt-dlp to re-extract the media.",
    )
    parser.add_argument(
        "-N",
        "--concurrent-fragments",
        type=int,
        metavar="N",
        help="Download N fragments concurrently for DASH/HLS-native media.",
    )
    parser.add_argument(
        "-R",
        "--retries",
        metavar="RETRIES",
        help="Set yt-dlp download retries to a non-negative integer or 'infinite'.",
    )
    parser.add_argument(
        "--fragment-retries",
        metavar="RETRIES",
        help="Set fragment retries to a non-negative integer or 'infinite'.",
    )
    parser.add_argument(
        "--file-access-retries",
        metavar="RETRIES",
        help="Set file-access retries to a non-negative integer or 'infinite'.",
    )
    parser.add_argument(
        "--extractor-retries",
        metavar="RETRIES",
        help="Set extractor retries to a non-negative integer or 'infinite'.",
    )
    parser.add_argument(
        "--retry-sleep",
        action="append",
        metavar="[TYPE:]EXPR",
        help="Add one yt-dlp retry-sleep expression. Repeat the option for multiple retry types.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        metavar="FILE",
        help=f"Use FILE as the yt-dlp download archive (built-in default: {ARCHIVE_FILE}).",
    )
    parser.add_argument(
        "--temp-path",
        type=Path,
        metavar="DIR",
        help=f"Use DIR for yt-dlp temporary/intermediate files (built-in default: {TEMP_DIR}).",
    )
    parser.add_argument(
        "--extractor-args",
        action="append",
        metavar="IE_KEY:ARGS",
        help="Add one yt-dlp extractor-argument string. Repeat to configure multiple extractors.",
    )
    parser.add_argument(
        "--playlist-index",
        dest="playlist_items",
        action=PlaylistIndexAction,
        type=int,
        metavar="INDEX",
        help=(
            "Select one 1-based playlist INDEX. Repeat to select several entries; negative indices count from the end."
        ),
    )
    parser.add_argument(
        "--playlist-range",
        dest="playlist_items",
        action=PlaylistRangeAction,
        nargs=2,
        type=int,
        metavar=("START", "STOP"),
        help="Select an inclusive playlist range START..STOP. Repeat to add further ranges.",
    )
    parser.add_argument(
        "--playlist-slice",
        dest="playlist_items",
        action=PlaylistSliceAction,
        metavar="[START]:[STOP][:STEP]",
        help="Select a playlist slice using 1-based yt-dlp slice bounds. STEP must not be zero.",
    )
    reverse_group = parser.add_mutually_exclusive_group()
    reverse_group.add_argument(
        "--rev",
        "--reverse-playlist",
        dest="reverse_playlist",
        action="store_true",
        default=None,
        help="Ask yt-dlp to traverse playlists in reverse order.",
    )
    reverse_group.add_argument(
        "--playlist-forward",
        "--no-reverse-playlist",
        dest="reverse_playlist",
        action="store_false",
        help="Disable reverse playlist traversal, overriding a parameter profile.",
    )
    playlist_group = parser.add_mutually_exclusive_group()
    playlist_group.add_argument(
        "--playlist",
        dest="playlist",
        action="store_true",
        default=None,
        help="Explicitly allow playlist traversal for this invocation.",
    )
    playlist_group.add_argument(
        "--no-playlist",
        dest="playlist",
        action="store_false",
        help="Download only the referenced item rather than its containing playlist.",
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        metavar="FILE",
        help="Read targets from FILE instead of positional targets or ./ids.txt.",
    )
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument(
        "--cookies",
        type=Path,
        metavar="FILE",
        help=(
            "Use cookies from FILE. If omitted, cookies.txt beside this script is used "
            "when present; otherwise yt-dlp runs without cookies."
        ),
    )
    cookie_group.add_argument(
        "--cookies-from-browser",
        metavar="BROWSER[+KEYRING][:PROFILE][::CONTAINER]",
        help="Load cookies directly from a browser using yt-dlp's browser-cookie specification.",
    )
    cookie_group.add_argument(
        "--no-cookies",
        action="store_true",
        default=None,
        help="Do not use cookies, even if cookies.txt exists beside this script.",
    )
    cookie_group.add_argument(
        "--auto-cookies",
        action="store_true",
        default=None,
        help="Restore automatic script-local cookie discovery, overriding a parameter profile.",
    )
    explain_group = parser.add_mutually_exclusive_group()
    explain_group.add_argument(
        "--explain",
        action="store_true",
        help="Describe the resolved download plan without running yt-dlp.",
    )
    explain_group.add_argument(
        "--explain-json",
        action="store_true",
        help="Emit the resolved download plan as JSON without running yt-dlp.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved yt-dlp command without running it.",
    )
    parser.add_argument(
        "--remove-completed-ids",
        action="store_true",
        help=(
            "When input comes from a file, remove each exact video ID from that "
            "file immediately when yt-dlp completes it, or when the same ID is "
            "already recorded in the configured download archive."
        ),
    )
    parser.add_argument(
        "--queue-report",
        type=Path,
        metavar="FILE",
        help=("Write a JSON queue outcome report to FILE. Requires --remove-completed-ids and file-backed input."),
    )
    parser.add_argument(
        "--failed-targets",
        type=Path,
        metavar="FILE",
        help=(
            "After a queue run, atomically write targets whose successful completion "
            "was not established to FILE. Requires --remove-completed-ids."
        ),
    )
    parser.add_argument(
        "--run-manifest",
        type=Path,
        metavar="FILE",
        help="Write a redacted machine-readable manifest describing this actual download run.",
    )
    parser.add_argument(
        "--hash-outputs",
        action="store_true",
        help="Include SHA-256 hashes for completed primary outputs in --run-manifest.",
    )
    parser.add_argument(
        "--_remove-completed-id",
        nargs=2,
        metavar=("FILE", "VIDEO_ID"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--_record-output",
        nargs=3,
        metavar=("LEDGER", "MEDIA_ID", "OUTPUT_PATH"),
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Show practical usage examples and exit.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PROGRAM_VERSION}",
    )
    return parser


def show_examples(parser: argparse.ArgumentParser) -> None:
    """Print the extended examples text without requiring a configured system."""
    print(EXAMPLES % {"prog": parser.prog})


def validate_resolution(value: str) -> str:
    """Validate and normalise a resolution used for yt-dlp format sorting."""
    value = value.strip().lower()
    if value == "best":
        return value
    if value.endswith("p"):
        value = value[:-1]
    if not value:
        raise ValueError("resolution must not be empty")
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(
            f"invalid resolution {value!r}; expected 'best' or a positive number such as 1080, 1440p or 2160p"
        )
    return value


def resolve_input(args: argparse.Namespace) -> InputSource:
    """Resolve command-line input into one unambiguous source."""
    targets: list[str] = args.targets

    if args.input_file is not None:
        if targets:
            raise ValueError("--input-file cannot be combined with positional targets")
        return _batch_file_source(args.input_file)

    if not targets:
        return _batch_file_source(DEFAULT_VIDEO_ID_FILE)

    if "-" in targets:
        if len(targets) != 1:
            raise ValueError("'-' for standard input cannot be combined with other targets")
        return InputSource(stdin=True)

    if len(targets) == 1:
        possible_file = Path(targets[0]).expanduser()
        if possible_file.is_file():
            return _batch_file_source(possible_file)

    return InputSource(direct_targets=tuple(targets))


def _batch_file_source(path: Path) -> InputSource:
    """Validate and return a batch-file input source."""
    expanded = path.expanduser()
    if not expanded.is_file():
        raise ValueError(f"input file not found: {expanded}")
    return InputSource(batch_file=expanded)


def _looks_like_explicit_path(value: str) -> bool:
    """Return whether a profile argument should be interpreted as a path."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return True
    if value.startswith((".", "~")):
        return True
    if os.sep in value:
        return True
    return bool(os.altsep and os.altsep in value)


def profile_path(value: str) -> Path:
    """Resolve a profile name or explicit path to one filesystem path."""
    if _looks_like_explicit_path(value):
        return Path(value).expanduser()
    return PROFILES_DIR / value


def parse_profile(path: Path) -> OutputProfile:
    """Parse and validate one existing output profile.

    The first non-empty line must be ``@profile``. Subsequent blank lines and
    comments beginning with ``#`` are ignored. Recognised keys are ``path`` and
    ``output``. Keys are case-insensitive and may appear at most once.
    """
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"profile is not valid UTF-8 text: {path}") from exc
    except OSError as exc:
        raise ValueError(f"unable to read profile {path}: {exc}") from exc

    lines = text.splitlines()
    first_content_index: int | None = None
    for index, line in enumerate(lines):
        if line.strip():
            first_content_index = index
            break

    if first_content_index is None:
        raise ValueError(f"profile is empty: {path}")

    signature = lines[first_content_index].strip()
    if signature != PROFILE_SIGNATURE:
        raise ValueError(f"invalid profile {path}: expected {PROFILE_SIGNATURE!r} on the first non-empty line")

    settings: dict[str, str] = {}
    recognised = {"path", "output"}

    for line_number, raw_line in enumerate(lines[first_content_index + 1 :], start=first_content_index + 2):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@"):
            raise ValueError(f"invalid profile {path}, line {line_number}: unknown directive {stripped!r}")
        if "=" not in raw_line:
            raise ValueError(f"invalid profile {path}, line {line_number}: expected KEY=VALUE")

        raw_key, raw_value = raw_line.split("=", 1)
        key = raw_key.strip().lower()
        value = raw_value.strip()

        if key not in recognised:
            hint = " Did you mean 'path'?" if key == "paht" else ""
            raise ValueError(f"invalid profile {path}, line {line_number}: unknown setting {key!r}.{hint}")
        if key in settings:
            raise ValueError(f"invalid profile {path}, line {line_number}: duplicate setting {key!r}")
        if not value:
            raise ValueError(f"invalid profile {path}, line {line_number}: setting {key!r} must not be empty")
        settings[key] = value

    if not settings:
        raise ValueError(f"invalid profile {path}: define at least one of 'path' or 'output'")

    return OutputProfile(
        source=path,
        path=settings.get("path"),
        output=settings.get("output"),
    )


def resolve_profile(requested: str | None) -> OutputProfile | None:
    """Resolve a requested profile with fallback to ``profiles/default``.

    Missing profiles are recoverable. Existing but invalid profiles are not.
    ``None`` means yt-dlp should use its native output location and naming.
    """
    default_path = PROFILES_DIR / DEFAULT_PROFILE_NAME

    if requested is not None:
        requested_path = profile_path(requested)
        if requested_path.is_file():
            return parse_profile(requested_path)

        print(
            f"Warning: profile {requested!r} was not found at {requested_path}. Trying {default_path}.",
            file=sys.stderr,
        )

    if default_path.is_file():
        return parse_profile(default_path)

    if requested is not None:
        print(
            "Warning: default profile was not found. Using yt-dlp's native output defaults.",
            file=sys.stderr,
        )

    return None


def validate_parameter_profile_name(name: str) -> str:
    """Validate a parameter-profile name used as a JSON object key."""
    if not PARAMETER_PROFILE_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid parameter profile name {name!r}; use letters, numbers, '.', '_' or '-'")
    return name


def _validate_rate_setting(key: str, value: object) -> str:
    """Validate a yt-dlp byte-rate setting without accepting arbitrary option text."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"parameter setting {key!r} must be a non-empty JSON string")
    normalised = value.strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?[KMGTP]?", normalised, flags=re.IGNORECASE):
        raise ValueError(f"parameter setting {key!r} must be a yt-dlp byte rate such as '500K' or '20M'")
    return normalised


def _validate_retry_setting(key: str, value: object) -> str:
    """Validate a retry count accepted by yt-dlp."""
    if isinstance(value, bool):
        raise ValueError(f"parameter setting {key!r} must be an integer or 'infinite'")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"parameter setting {key!r} must not be negative")
        return str(value)
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised == "infinite" or normalised.isdigit():
            return normalised
    raise ValueError(f"parameter setting {key!r} must be a non-negative integer or 'infinite'")


def _validate_string_list_setting(key: str, value: object) -> list[str]:
    """Validate a profile setting represented by one or more non-empty strings."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"parameter setting {key!r} must be a non-empty JSON array of strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"parameter setting {key!r} must contain only non-empty JSON strings")
        result.append(item.strip())
    return result


def _validate_positive_integer_setting(key: str, value: object) -> int:
    """Validate a strictly positive JSON integer setting."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"parameter setting {key!r} must be a positive JSON integer")
    return value


def _validate_resolution_bound_setting(key: str, value: object) -> int:
    """Validate a hard vertical-resolution bound."""
    if isinstance(value, bool):
        raise ValueError(f"parameter setting {key!r} must be a positive integer or numeric string")
    text = str(value).strip().lower()
    if text.endswith("p"):
        text = text[:-1]
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"parameter setting {key!r} must be a positive integer or numeric string")
    return int(text)


def _validate_codec_setting(key: str, value: object) -> str:
    """Validate a codec preference without accepting format-expression syntax."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value.strip()):
        raise ValueError(f"parameter setting {key!r} must be a codec name such as 'av01', 'vp9' or 'opus'")
    return value.strip().lower()


def _validate_nonempty_string_setting(key: str, value: object) -> str:
    """Validate an intentionally opaque non-empty yt-dlp string setting."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"parameter setting {key!r} must be a non-empty JSON string")
    return value.strip()


def _validate_audio_source_container_setting(key: str, value: object) -> str:
    """Validate an exact source extension/container token."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", value.strip()):
        raise ValueError(f"parameter setting {key!r} must be a simple container/extension name")
    return value.strip().lower()


def _validate_audio_format_setting(value: object) -> str:
    """Validate a yt-dlp audio conversion format."""
    if not isinstance(value, str) or value.lower() not in SUPPORTED_AUDIO_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_FORMATS))
        raise ValueError(f"parameter setting 'audio-format' must be one of: {supported}")
    return value.lower()


def _validate_audio_quality_setting(value: object) -> str:
    """Validate yt-dlp's documented VBR or bitrate audio-quality syntax."""
    if isinstance(value, bool):
        raise ValueError("parameter setting 'audio-quality' must be 0..10 or a bitrate such as '128K'")
    if isinstance(value, int):
        if 0 <= value <= 10:
            return str(value)
        raise ValueError("parameter setting 'audio-quality' integer must be between 0 and 10")
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"(?:10|[0-9])", text):
            return text
        if re.fullmatch(r"[1-9][0-9]*(?:\.[0-9]+)?[KkMm]", text):
            return text.upper()
    raise ValueError("parameter setting 'audio-quality' must be 0..10 or a bitrate such as '128K'")


def _validate_sponsorblock_categories(key: str, value: object) -> str:
    """Validate SponsorBlock category expressions while preserving exclusion order."""
    text = _validate_nonempty_string_setting(key, value)
    allowed = SPONSORBLOCK_MARK_CATEGORIES if key == "sponsorblock-mark" else SPONSORBLOCK_REMOVE_CATEGORIES
    categories = [item.strip() for item in text.split(",")]
    if any(not item for item in categories):
        raise ValueError(f"parameter setting {key!r} contains an empty SponsorBlock category")
    for item in categories:
        category = item[1:] if item.startswith("-") else item
        if category not in allowed:
            supported = ", ".join(sorted(allowed))
            raise ValueError(
                f"parameter setting {key!r} contains unsupported SponsorBlock category {category!r}; "
                f"expected one of: {supported}"
            )
    return ",".join(categories)


def _validate_wait_for_video_setting(value: object) -> str:
    """Validate yt-dlp's scheduled-stream wait interval without accepting option text."""
    if isinstance(value, bool):
        raise ValueError("parameter setting 'wait-for-video' must be MIN or MIN-MAX seconds")
    text = str(value).strip()
    match = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", text)
    if match is None:
        raise ValueError("parameter setting 'wait-for-video' must be MIN or MIN-MAX seconds")
    minimum = int(match.group(1))
    maximum = int(match.group(2)) if match.group(2) is not None else None
    if minimum < 1 or (maximum is not None and maximum < minimum):
        raise ValueError("parameter setting 'wait-for-video' requires MIN >= 1 and MAX >= MIN")
    return str(minimum) if maximum is None else f"{minimum}-{maximum}"


def _validate_playlist_index(value: object, *, label: str = "playlist index") -> int:
    """Validate one 1-based playlist index, allowing negative offsets from the end."""
    if isinstance(value, bool) or not isinstance(value, int) or value == 0:
        raise ValueError(f"{label} must be a non-zero integer")
    return value


def _normalise_playlist_slice(value: object) -> str:
    """Validate and canonicalise one yt-dlp playlist slice expression."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("playlist slice must be a non-empty string")
    text = value.strip()
    parts = text.split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("playlist slice must use [START]:[STOP][:STEP] syntax")
    normalised: list[str] = []
    for position, part in enumerate(parts):
        if part == "":
            normalised.append("")
            continue
        try:
            number = int(part, 10)
        except ValueError as exc:
            raise ValueError("playlist slice bounds and step must be integers") from exc
        if position < 2 and number == 0:
            raise ValueError("playlist slice START and STOP must be non-zero when supplied")
        if position == 2 and number == 0:
            raise ValueError("playlist slice STEP must not be zero")
        normalised.append(str(number))
    if not normalised[0] and not normalised[1] and (len(normalised) == 2 or not normalised[2]):
        raise ValueError("playlist slice must constrain a bound or provide a non-default step")
    return ":".join(normalised)


def _validate_playlist_items_setting(value: object) -> list[str]:
    """Validate canonical playlist index/range/slice expressions from a parameter profile."""
    if not isinstance(value, list) or not value:
        raise ValueError("parameter setting 'playlist-items' must be a non-empty JSON array")
    result: list[str] = []
    for item in value:
        if isinstance(item, bool):
            raise ValueError("parameter setting 'playlist-items' entries must be integers or slice strings")
        if isinstance(item, int):
            result.append(str(_validate_playlist_index(item, label="playlist-items index")))
            continue
        if isinstance(item, str):
            text = item.strip()
            if re.fullmatch(r"[+-]?[0-9]+", text):
                result.append(str(_validate_playlist_index(int(text, 10), label="playlist-items index")))
            else:
                try:
                    result.append(_normalise_playlist_slice(text))
                except ValueError as exc:
                    raise ValueError(f"invalid playlist-items entry {item!r}: {exc}") from exc
            continue
        raise ValueError("parameter setting 'playlist-items' entries must be integers or slice strings")
    return result


def _cli_playlist_items(args: argparse.Namespace) -> list[str] | None:
    """Return canonical typed playlist selectors supplied on the CLI."""
    values = getattr(args, "playlist_items", None)
    return list(values) if values else None


def _normalise_section_timestamp(value: object, *, allow_inf: bool) -> str:
    """Validate one partial-media timestamp without silently changing its meaning."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("section timestamp must be a non-empty string")
    text = value.strip().lower()
    if allow_inf and text == "inf":
        return text
    if not re.fullmatch(r"-?(?:\d+(?:\.\d+)?|\d+:[0-5]?\d(?:\.\d+)?|\d+:[0-5]?\d:[0-5]?\d(?:\.\d+)?)", text):
        raise ValueError(f"invalid section timestamp {value!r}")
    body = text[1:] if text.startswith("-") else text
    parts = body.split(":")
    if len(parts) >= 2:
        if int(parts[-2]) >= 60:
            raise ValueError(f"invalid section timestamp {value!r}: minutes must be below 60")
        if float(parts[-1]) >= 60:
            raise ValueError(f"invalid section timestamp {value!r}: seconds must be below 60")
    return text


def _normalise_time_range(value: object) -> str:
    """Validate one START/STOP pair and return yt-dlp's canonical range syntax."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError("time range must contain exactly START and STOP")
    start = _normalise_section_timestamp(value[0], allow_inf=False)
    stop = _normalise_section_timestamp(value[1], allow_inf=True)
    if stop != "inf" and not start.startswith("-") and not stop.startswith("-"):

        def seconds(text: str) -> float:
            result = 0.0
            for part in text.split(":"):
                result = result * 60 + float(part)
            return result

        if seconds(stop) <= seconds(start):
            raise ValueError("time range STOP must be later than START")
    return f"{start}-{stop}"


def _validate_chapter_sections_setting(value: object) -> list[str]:
    """Validate chapter regexes from a parameter profile."""
    if not isinstance(value, list) or not value:
        raise ValueError("parameter setting 'chapter-sections' must be a non-empty JSON array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("parameter setting 'chapter-sections' entries must be non-empty strings")
        try:
            re.compile(item)
        except re.error as exc:
            raise ValueError(f"invalid chapter section regular expression {item!r}: {exc}") from exc
        result.append(item)
    return result


def _validate_time_ranges_setting(value: object) -> list[str]:
    """Validate time ranges from a parameter profile."""
    if not isinstance(value, list) or not value:
        raise ValueError("parameter setting 'time-ranges' must be a non-empty JSON array")
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            match = re.fullmatch(r"(-?[^-]+)-(-?.+)", item.strip(), re.IGNORECASE)
            if match is None:
                raise ValueError(f"invalid time-ranges entry {item!r}")
            result.append(_normalise_time_range((match.group(1), match.group(2))))
        elif isinstance(item, list) and len(item) == 2:
            result.append(_normalise_time_range(item))
        else:
            raise ValueError("parameter setting 'time-ranges' entries must be strings or two-item arrays")
    return result


def _validate_parameter_setting(key: str, value: object) -> object:
    """Validate one parameter-profile setting and return its normalised value."""
    if key == "resolution":
        if not isinstance(value, str):
            raise ValueError("parameter setting 'resolution' must be a JSON string")
        validate_resolution(value)
        return value
    if key == "format":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("parameter setting 'format' must be a non-empty JSON string")
        return value.strip()
    if key in {"cookies", "archive", "temp-path"}:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"parameter setting {key!r} must be a non-empty JSON string")
        return value.strip()
    if key == "cookies-from-browser":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("parameter setting 'cookies-from-browser' must be a non-empty JSON string")
        normalised = value.strip()
        browser = re.split(r"[+:]", normalised, maxsplit=1)[0].lower()
        if browser not in SUPPORTED_COOKIE_BROWSERS:
            supported = ", ".join(sorted(SUPPORTED_COOKIE_BROWSERS))
            raise ValueError(
                f"parameter setting 'cookies-from-browser' uses unsupported browser {browser!r}; "
                f"expected one of: {supported}"
            )
        return normalised
    if key in {"min-resolution", "max-resolution"}:
        return _validate_resolution_bound_setting(key, value)
    if key in {"min-fps", "max-fps", "preferred-fps", "preferred-audio-channels"}:
        return _validate_positive_integer_setting(key, value)
    if key in {"preferred-video-codec", "preferred-audio-codec", "audio-source-codec"}:
        return _validate_codec_setting(key, value)
    if key == "audio-source-container":
        return _validate_audio_source_container_setting(key, value)
    if key == "audio-format":
        return _validate_audio_format_setting(value)
    if key == "audio-quality":
        return _validate_audio_quality_setting(value)
    if key == "preferred-hdr":
        if not isinstance(value, str) or value.lower() not in {"sdr", "hdr", "dv"}:
            raise ValueError("parameter setting 'preferred-hdr' must be one of: sdr, hdr, dv")
        return value.lower()
    if key == "merge-container":
        if not isinstance(value, str) or value.lower() not in SUPPORTED_MERGE_CONTAINERS:
            supported = ", ".join(sorted(SUPPORTED_MERGE_CONTAINERS))
            raise ValueError(f"parameter setting 'merge-container' must be one of: {supported}")
        return value.lower()
    if key in {"limit-rate", "throttled-rate"}:
        return _validate_rate_setting(key, value)
    if key == "concurrent-fragments":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("parameter setting 'concurrent-fragments' must be a positive JSON integer")
        return value
    if key in {"retries", "fragment-retries", "file-access-retries", "extractor-retries"}:
        return _validate_retry_setting(key, value)
    if key in {"retry-sleep", "extractor-args"}:
        return _validate_string_list_setting(key, value)
    if key == "playlist-items":
        return _validate_playlist_items_setting(value)
    if key == "wait-for-video":
        return _validate_wait_for_video_setting(value)
    if key == "chapter-sections":
        return _validate_chapter_sections_setting(value)
    if key == "time-ranges":
        return _validate_time_ranges_setting(value)
    if key in {"sub-langs", "sub-format"}:
        return _validate_nonempty_string_setting(key, value)
    if key in {"sponsorblock-mark", "sponsorblock-remove"}:
        return _validate_sponsorblock_categories(key, value)
    if key in {
        "no-cookies",
        "reverse-playlist",
        "playlist",
        "write-subs",
        "write-auto-subs",
        "embed-subs",
        "write-thumbnail",
        "embed-thumbnail",
        "write-info-json",
        "embed-metadata",
        "embed-chapters",
        "sponsorblock",
        "audio-only",
        "audio-source-fallback",
        "live",
        "live-from-start",
        "write-live-chat",
    }:
        if not isinstance(value, bool):
            raise ValueError(f"parameter setting {key!r} must be a JSON Boolean")
        return value
    raise ValueError(f"unknown parameter setting {key!r}")


def _json_schema_string(*, description: str, pattern: str | None = None) -> dict[str, object]:
    """Build one non-empty string-valued JSON Schema property."""
    result: dict[str, object] = {
        "type": "string",
        "minLength": 1,
        "pattern": pattern or r"\S",
        "description": description,
    }
    return result


def _json_schema_boolean(*, description: str) -> dict[str, object]:
    """Build one Boolean JSON Schema property."""
    return {"type": "boolean", "description": description}


def _json_schema_positive_integer(*, description: str) -> dict[str, object]:
    """Build one positive-integer JSON Schema property."""
    return {"type": "integer", "minimum": 1, "description": description}


def parameter_profile_setting_schema() -> dict[str, object]:
    """Return JSON Schema for one parameter-profile settings object.

    JSON Schema describes structural constraints. Cross-field comparisons and
    yt-dlp expression validation that cannot be represented faithfully remain
    runtime semantic checks and are listed in the surrounding machine contract.
    """
    descriptions = PARAMETER_SETTING_DESCRIPTIONS
    boolean_keys = {
        "no-cookies",
        "reverse-playlist",
        "playlist",
        "live",
        "live-from-start",
        "write-live-chat",
        "audio-only",
        "audio-source-fallback",
        "write-subs",
        "write-auto-subs",
        "embed-subs",
        "write-thumbnail",
        "embed-thumbnail",
        "write-info-json",
        "embed-metadata",
        "embed-chapters",
        "sponsorblock",
    }
    positive_integer_keys = {
        "concurrent-fragments",
        "min-fps",
        "max-fps",
        "preferred-fps",
        "preferred-audio-channels",
    }
    properties: dict[str, object] = {}
    for key in boolean_keys:
        properties[key] = _json_schema_boolean(description=descriptions[key])
    for key in positive_integer_keys:
        properties[key] = _json_schema_positive_integer(description=descriptions[key])

    properties.update(
        {
            "resolution": _json_schema_string(
                description=descriptions["resolution"],
                pattern=r"^(?:[bB][eE][sS][tT]|[1-9][0-9]*[pP]?)$",
            ),
            "format": _json_schema_string(description=descriptions["format"]),
            "cookies": _json_schema_string(description=descriptions["cookies"]),
            "cookies-from-browser": _json_schema_string(description=descriptions["cookies-from-browser"]),
            "playlist-items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "oneOf": [
                        {"type": "integer", "not": {"const": 0}},
                        {"type": "string", "minLength": 1},
                    ]
                },
                "description": descriptions["playlist-items"],
            },
            "wait-for-video": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": r"^[0-9]+(?:-[0-9]+)?$"},
                ],
                "description": descriptions["wait-for-video"],
            },
            "chapter-sections": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
                "description": descriptions["chapter-sections"],
            },
            "time-ranges": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "oneOf": [
                        {"type": "string", "minLength": 1},
                        {
                            "type": "array",
                            "prefixItems": [{"type": "string"}, {"type": "string"}],
                            "minItems": 2,
                            "maxItems": 2,
                        },
                    ]
                },
                "description": descriptions["time-ranges"],
            },
            "limit-rate": _json_schema_string(description=descriptions["limit-rate"]),
            "throttled-rate": _json_schema_string(description=descriptions["throttled-rate"]),
            "retries": {
                "oneOf": [
                    {"type": "integer", "minimum": 0},
                    {"type": "string", "pattern": r"^(?:infinite|[0-9]+)$"},
                ],
                "description": descriptions["retries"],
            },
            "fragment-retries": {
                "oneOf": [
                    {"type": "integer", "minimum": 0},
                    {"type": "string", "pattern": r"^(?:infinite|[0-9]+)$"},
                ],
                "description": descriptions["fragment-retries"],
            },
            "file-access-retries": {
                "oneOf": [
                    {"type": "integer", "minimum": 0},
                    {"type": "string", "pattern": r"^(?:infinite|[0-9]+)$"},
                ],
                "description": descriptions["file-access-retries"],
            },
            "extractor-retries": {
                "oneOf": [
                    {"type": "integer", "minimum": 0},
                    {"type": "string", "pattern": r"^(?:infinite|[0-9]+)$"},
                ],
                "description": descriptions["extractor-retries"],
            },
            "retry-sleep": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
                "description": descriptions["retry-sleep"],
            },
            "archive": _json_schema_string(description=descriptions["archive"]),
            "temp-path": _json_schema_string(description=descriptions["temp-path"]),
            "extractor-args": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
                "description": descriptions["extractor-args"],
            },
            "min-resolution": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": r"^[1-9][0-9]*[pP]?$"},
                ],
                "description": descriptions["min-resolution"],
            },
            "max-resolution": {
                "oneOf": [
                    {"type": "integer", "minimum": 1},
                    {"type": "string", "pattern": r"^[1-9][0-9]*[pP]?$"},
                ],
                "description": descriptions["max-resolution"],
            },
            "preferred-video-codec": _json_schema_string(description=descriptions["preferred-video-codec"]),
            "preferred-audio-codec": _json_schema_string(description=descriptions["preferred-audio-codec"]),
            "preferred-hdr": {
                **_json_schema_string(
                    description=descriptions["preferred-hdr"],
                    pattern=r"^(?:[sS][dD][rR]|[hH][dD][rR]|[dD][vV])$",
                ),
                "x-downloader-canonical-values": ["sdr", "hdr", "dv"],
            },
            "merge-container": {
                **_json_schema_string(
                    description=descriptions["merge-container"],
                    pattern=r"^(?:[aA][vV][iI]|[fF][lL][vV]|[mM][kK][vV]|[mM][oO][vV]|[mM][pP]4|[wW][eE][bB][mM])$",
                ),
                "x-downloader-canonical-values": sorted(SUPPORTED_MERGE_CONTAINERS),
            },
            "audio-source-codec": _json_schema_string(description=descriptions["audio-source-codec"]),
            "audio-source-container": _json_schema_string(description=descriptions["audio-source-container"]),
            "audio-format": {
                **_json_schema_string(
                    description=descriptions["audio-format"],
                    pattern=r"^(?:[bB][eE][sS][tT]|[aA][aA][cC]|[aA][lL][aA][cC]|[fF][lL][aA][cC]|[mM]4[aA]|[mM][pP]3|[oO][pP][uU][sS]|[vV][oO][rR][bB][iI][sS]|[wW][aA][vV])$",
                ),
                "x-downloader-canonical-values": sorted(SUPPORTED_AUDIO_FORMATS),
            },
            "audio-quality": {
                "oneOf": [
                    {"type": "integer", "minimum": 0, "maximum": 10},
                    {"type": "string", "pattern": r"^(?:10|[0-9]|[1-9][0-9]*(?:\.[0-9]+)?[KkMm])$"},
                ],
                "description": descriptions["audio-quality"],
            },
            "sub-langs": _json_schema_string(description=descriptions["sub-langs"]),
            "sub-format": _json_schema_string(description=descriptions["sub-format"]),
            "sponsorblock-mark": _json_schema_string(description=descriptions["sponsorblock-mark"]),
            "sponsorblock-remove": _json_schema_string(description=descriptions["sponsorblock-remove"]),
        }
    )

    missing = set(PARAMETER_PROFILE_KEYS) - set(properties)
    extra = set(properties) - set(PARAMETER_PROFILE_KEYS)
    if missing or extra:
        raise RuntimeError(
            "parameter-profile schema metadata is out of sync with runtime keys: "
            f"missing={sorted(missing)!r}, extra={sorted(extra)!r}"
        )

    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": "urn:yt-media-tools:downloader:parameter-settings:1",
        "title": "yt-downloader parameter-profile settings",
        "type": "object",
        "additionalProperties": False,
        "properties": {key: properties[key] for key in PARAMETER_PROFILE_KEYS},
        "allOf": [
            {
                "not": {
                    "anyOf": [
                        {"required": ["cookies", "cookies-from-browser"]},
                        {"required": ["cookies", "no-cookies"]},
                        {"required": ["cookies-from-browser", "no-cookies"]},
                    ]
                }
            },
            {
                "if": {"required": ["audio-quality"]},
                "then": {"required": ["audio-format"]},
            },
            {
                "if": {"properties": {"playlist": {"const": False}}, "required": ["playlist"]},
                "then": {"not": {"required": ["playlist-items"]}},
            },
            *[
                {
                    "if": {"properties": {key: {"const": True}}, "required": [key]},
                    "then": {"properties": {"live": {"const": True}}, "required": ["live"]},
                }
                for key in ("live-from-start", "write-live-chat")
            ],
            {
                "if": {"required": ["wait-for-video"]},
                "then": {"properties": {"live": {"const": True}}, "required": ["live"]},
            },
        ],
    }


def parameter_profile_file_schema() -> dict[str, object]:
    """Return JSON Schema for the complete versioned defaults/profile file."""
    settings_schema = parameter_profile_setting_schema()
    embedded_settings = {key: value for key, value in settings_schema.items() if key not in {"$schema", "$id"}}
    return {
        "$schema": JSON_SCHEMA_DIALECT,
        "$id": "urn:yt-media-tools:downloader:parameter-profiles:1",
        "title": "yt-downloader parameter profiles",
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "profiles"],
        "$defs": {"settings": embedded_settings},
        "properties": {
            "version": {"const": PARAMETER_PROFILE_VERSION},
            "profiles": {
                "type": "object",
                "propertyNames": {"pattern": PARAMETER_PROFILE_NAME_RE.pattern},
                "additionalProperties": {"$ref": "#/$defs/settings"},
            },
        },
    }


def machine_contract() -> dict[str, object]:
    """Return the versioned language-neutral machine contract descriptor."""
    return {
        "contract_version": MACHINE_CONTRACT_VERSION,
        "downloader": {"name": PROGRAM_NAME, "version": PROGRAM_VERSION},
        "json_schema_dialect": JSON_SCHEMA_DIALECT,
        "parameter_profiles": {
            "format_version": PARAMETER_PROFILE_VERSION,
            "file_schema": parameter_profile_file_schema(),
            "settings_schema": parameter_profile_setting_schema(),
            "precedence": ["explicit-cli", "parameter-profile", "built-in-defaults"],
            "unknown_settings": "error",
            "semantic_validation": [
                "minimum resolution must not exceed maximum resolution",
                "minimum FPS must not exceed maximum FPS",
                "yt-dlp expression-valued settings are validated by Downloader where a stable grammar is owned",
                "partial-media timestamps and chapter regular expressions receive additional runtime validation",
                "the schema describes canonical machine-facing values while runtime validation may normalise equivalent text forms",
                "cross-policy conflicts that depend on resolved CLI state are validated after precedence resolution",
            ],
        },
        "machine_interfaces": {
            "schema": {"cli": "--schema-json", "stability": "versioned"},
            "config_validation": {
                "cli": "--validate-config [FILE]",
                "schema_version": CONFIG_VALIDATION_SCHEMA_VERSION,
                "stability": "versioned",
            },
            "capabilities": {
                "cli": ["--capabilities", "--capabilities-json"],
                "schema_version": CAPABILITIES_SCHEMA_VERSION,
                "stability": "versioned",
            },
            "explain": {
                "cli": "--explain-json",
                "schema_version": PLAN_SCHEMA_VERSION,
                "stability": "versioned",
            },
            "run_manifest": {"schema_version": RUN_MANIFEST_SCHEMA_VERSION, "stability": "versioned"},
        },
        "future_machine_interfaces": {
            "execution_request_schema": "planned",
            "structured_per_target_outcomes": "investigate",
            "manifest_retry": "depends-on-structured-outcomes",
            "discover_interchange": "planned",
        },
    }


def emit_machine_contract() -> None:
    """Write the machine contract as deterministic UTF-8 JSON."""
    print(json.dumps(machine_contract(), indent=2, sort_keys=True))


def validate_config_file(path: Path) -> dict[str, object]:
    """Validate a complete parameter-profile file using Downloader's runtime rules."""
    profiles = load_parameter_profiles(path, allow_missing=False)
    return {
        "kind": "yt-download-config-validation",
        "schema_version": CONFIG_VALIDATION_SCHEMA_VERSION,
        "contract_version": MACHINE_CONTRACT_VERSION,
        "downloader_version": PROGRAM_VERSION,
        "path": str(path.expanduser().resolve()),
        "valid": True,
        "profile_count": len(profiles),
        "profiles": sorted(profiles),
    }


def _external_tool_capability(name: str) -> dict[str, object]:
    """Return conservative availability/version information for one external tool."""
    executable = shutil.which(name)
    if executable is None:
        return {"available": False, "executable": None, "version": None}
    version = None
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        first_line = (completed.stdout or completed.stderr).splitlines()
        if first_line:
            version = first_line[0].strip() or None
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": True, "executable": executable, "version": version}


def capabilities_payload() -> dict[str, object]:
    """Return versioned environment capabilities without implying extractor support."""
    return {
        "kind": "yt-download-capabilities",
        "schema_version": CAPABILITIES_SCHEMA_VERSION,
        "contract_version": MACHINE_CONTRACT_VERSION,
        "downloader": {"name": PROGRAM_NAME, "version": PROGRAM_VERSION},
        "external_tools": {
            "yt-dlp": _external_tool_capability("yt-dlp"),
            "ffmpeg": _external_tool_capability("ffmpeg"),
            "ffprobe": _external_tool_capability("ffprobe"),
        },
        "interfaces": {
            "schema_json": True,
            "config_validation": True,
            "capabilities_json": True,
            "explain_json": True,
            "run_manifest": True,
            "execution_request_schema": False,
            "structured_per_target_outcomes": False,
            "manifest_retry": False,
            "discover_interchange": False,
        },
        "notes": [
            "External-tool availability does not imply that every extractor or media workflow is supported.",
            "Extractor-specific capabilities remain yt-dlp and service dependent.",
        ],
    }


def format_capabilities(payload: dict[str, object]) -> str:
    """Return a concise human-readable capability report."""
    lines = [f"{PROGRAM_NAME} {PROGRAM_VERSION} capabilities"]
    tools = payload["external_tools"]
    assert isinstance(tools, dict)
    for name in ("yt-dlp", "ffmpeg", "ffprobe"):
        info = tools[name]
        assert isinstance(info, dict)
        if info["available"]:
            version = f" - {info['version']}" if info["version"] else ""
            lines.append(f"  {name}: available{version}")
        else:
            lines.append(f"  {name}: unavailable")
    return "\n".join(lines)


def validate_parameter_settings(settings: object, *, profile_name: str) -> dict[str, object]:
    """Validate a profile settings object without silently coercing JSON types."""
    if not isinstance(settings, dict):
        raise ValueError(f"parameter profile {profile_name!r} must be a JSON object")

    validated: dict[str, object] = {}
    for key, value in settings.items():
        if not isinstance(key, str):
            raise ValueError(f"parameter profile {profile_name!r} contains a non-string setting name")
        if key not in PARAMETER_PROFILE_KEYS:
            raise ValueError(f"parameter profile {profile_name!r} contains unknown option {key!r}")
        validated[key] = _validate_parameter_setting(key, value)

    cookie_keys = {"cookies", "cookies-from-browser", "no-cookies"} & set(validated)
    if len(cookie_keys) > 1:
        rendered = ", ".join(repr(key) for key in sorted(cookie_keys))
        raise ValueError(f"parameter profile {profile_name!r} cannot combine cookie settings: {rendered}")
    if (
        "min-resolution" in validated
        and "max-resolution" in validated
        and int(validated["min-resolution"]) > int(validated["max-resolution"])
    ):
        raise ValueError(f"parameter profile {profile_name!r} has min-resolution above max-resolution")
    if "min-fps" in validated and "max-fps" in validated and int(validated["min-fps"]) > int(validated["max-fps"]):
        raise ValueError(f"parameter profile {profile_name!r} has min-fps above max-fps")
    if "audio-quality" in validated and "audio-format" not in validated:
        raise ValueError(f"parameter profile {profile_name!r} cannot set audio-quality without audio-format")
    if validated.get("playlist") is False and "playlist-items" in validated:
        raise ValueError(f"parameter profile {profile_name!r} cannot combine playlist-items with playlist=false")
    live_options = {key for key in ("live-from-start", "write-live-chat") if validated.get(key) is True}
    if "wait-for-video" in validated:
        live_options.add("wait-for-video")
    if live_options and validated.get("live") is not True:
        rendered = ", ".join(sorted(live_options))
        raise ValueError(f"parameter profile {profile_name!r} requires live=true for: {rendered}")
    return validated


def defaults_path(requested: Path | None) -> Path:
    """Return the explicitly requested defaults file or the script-local default."""
    return requested.expanduser() if requested is not None else DEFAULTS_FILE


def load_parameter_profiles(path: Path, *, allow_missing: bool) -> dict[str, ParameterProfile]:
    """Load and strictly validate one versioned defaults JSON file."""
    if not path.is_file():
        if allow_missing:
            return {}
        raise ValueError(f"defaults file not found: {path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid defaults JSON in {path}: {exc.msg} at line {exc.lineno}, column {exc.colno}"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"unable to read defaults file {path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError(f"defaults file {path} must contain a JSON object")
    unknown_root = set(payload) - {"version", "profiles"}
    if unknown_root:
        rendered = ", ".join(repr(key) for key in sorted(unknown_root))
        raise ValueError(f"defaults file {path} contains unknown top-level key(s): {rendered}")
    if payload.get("version") != PARAMETER_PROFILE_VERSION:
        raise ValueError(
            f"defaults file {path} has unsupported version {payload.get('version')!r}; "
            f"expected {PARAMETER_PROFILE_VERSION}"
        )
    profiles_raw = payload.get("profiles")
    if not isinstance(profiles_raw, dict):
        raise ValueError(f"defaults file {path} must define a 'profiles' JSON object")

    profiles: dict[str, ParameterProfile] = {}
    for name, raw_settings in profiles_raw.items():
        if not isinstance(name, str):
            raise ValueError(f"defaults file {path} contains a non-string profile name")
        validate_parameter_profile_name(name)
        settings = validate_parameter_settings(raw_settings, profile_name=name)
        profiles[name] = ParameterProfile(name=name, settings=settings, source=path)
    return profiles


def select_parameter_profile(
    name: str | None,
    path: Path,
    *,
    explicit_defaults: bool,
) -> ParameterProfile | None:
    """Resolve one selected parameter profile, if requested."""
    if name is None:
        if explicit_defaults and not path.is_file():
            raise ValueError(f"defaults file not found: {path}")
        return None
    validate_parameter_profile_name(name)
    profiles = load_parameter_profiles(path, allow_missing=False)
    try:
        return profiles[name]
    except KeyError as exc:
        raise ValueError(f"parameter profile {name!r} was not found in {path}") from exc


def list_parameter_profiles(path: Path, *, explicit_defaults: bool) -> list[str]:
    """Return sorted parameter-profile names from one defaults file."""
    if not path.is_file() and not explicit_defaults:
        return []
    profiles = load_parameter_profiles(path, allow_missing=False)
    return sorted(profiles, key=str.casefold)


def explicit_parameter_settings(args: argparse.Namespace) -> dict[str, object]:
    """Return only profile-eligible settings explicitly supplied on the CLI."""
    settings: dict[str, object] = {}
    scalar_settings = {
        "resolution": args.resolution,
        "format": args.format_selector,
        "limit-rate": args.limit_rate,
        "throttled-rate": args.throttled_rate,
        "concurrent-fragments": args.concurrent_fragments,
        "retries": args.retries,
        "fragment-retries": args.fragment_retries,
        "file-access-retries": args.file_access_retries,
        "extractor-retries": args.extractor_retries,
        "min-resolution": args.min_resolution,
        "max-resolution": args.max_resolution,
        "min-fps": args.min_fps,
        "max-fps": args.max_fps,
        "preferred-fps": args.preferred_fps,
        "preferred-video-codec": args.preferred_video_codec,
        "preferred-audio-codec": args.preferred_audio_codec,
        "preferred-hdr": args.preferred_hdr,
        "preferred-audio-channels": args.preferred_audio_channels,
        "merge-container": args.merge_container,
        "audio-source-codec": args.audio_source_codec,
        "audio-source-container": args.audio_source_container,
        "audio-format": args.audio_format,
        "audio-quality": args.audio_quality,
        "sub-langs": args.sub_langs,
        "sub-format": args.sub_format,
        "sponsorblock-mark": args.sponsorblock_mark,
        "sponsorblock-remove": args.sponsorblock_remove,
        "wait-for-video": None if args.no_wait_for_video else args.wait_for_video,
    }
    for key, value in scalar_settings.items():
        if value is not None:
            settings[key] = _validate_parameter_setting(key, value)
    if args.retry_sleep is not None:
        settings["retry-sleep"] = _validate_parameter_setting("retry-sleep", args.retry_sleep)
    if args.chapter_sections is not None:
        settings["chapter-sections"] = _validate_parameter_setting("chapter-sections", args.chapter_sections)
    if args.time_ranges is not None:
        settings["time-ranges"] = [_normalise_time_range(value) for value in args.time_ranges]
    if args.whole_item:
        settings["_whole-item"] = True
    if args.no_wait_for_video:
        settings["wait-for-video"] = None
    if args.archive is not None:
        settings["archive"] = str(args.archive.expanduser())
    if args.temp_path is not None:
        settings["temp-path"] = str(args.temp_path.expanduser())
    if args.extractor_args is not None:
        settings["extractor-args"] = _validate_parameter_setting("extractor-args", args.extractor_args)
    for key, value in (
        ("write-subs", args.write_subs),
        ("write-auto-subs", args.write_auto_subs),
        ("embed-subs", args.embed_subs),
        ("write-thumbnail", args.write_thumbnail),
        ("embed-thumbnail", args.embed_thumbnail),
        ("write-info-json", args.write_info_json),
        ("embed-metadata", args.embed_metadata),
        ("embed-chapters", args.embed_chapters),
        ("sponsorblock", args.sponsorblock),
        ("audio-only", args.audio_only),
        ("audio-source-fallback", args.audio_source_fallback),
        ("live", args.live),
        ("live-from-start", args.live_from_start),
        ("write-live-chat", args.write_live_chat),
    ):
        if value is not None:
            settings[key] = value
    playlist_items = _cli_playlist_items(args)
    if playlist_items is not None:
        settings["playlist-items"] = playlist_items
    if args.reverse_playlist is not None:
        settings["reverse-playlist"] = args.reverse_playlist
    if args.playlist is not None:
        settings["playlist"] = args.playlist
    if args.cookies is not None:
        settings["cookies"] = str(args.cookies.expanduser())
    elif args.cookies_from_browser is not None:
        settings["cookies-from-browser"] = _validate_parameter_setting(
            "cookies-from-browser", args.cookies_from_browser
        )
    elif args.no_cookies is True:
        settings["no-cookies"] = True
    elif args.auto_cookies is True:
        settings["no-cookies"] = False
    return settings


def merge_parameter_settings(
    profile: ParameterProfile | None,
    cli_settings: dict[str, object],
) -> dict[str, object]:
    """Merge a selected profile with explicit CLI settings, with CLI precedence."""
    merged = dict(profile.settings) if profile is not None else {}
    if cookie_keys := ({"cookies", "cookies-from-browser", "no-cookies"} & set(cli_settings)):
        for key in {"cookies", "cookies-from-browser", "no-cookies"} - cookie_keys:
            merged.pop(key, None)
    sponsor_category_keys = {"sponsorblock-mark", "sponsorblock-remove"} & set(cli_settings)
    if sponsor_category_keys and "sponsorblock" not in cli_settings:
        merged.pop("sponsorblock", None)
    if cli_settings.get("sponsorblock") is False:
        merged.pop("sponsorblock-mark", None)
        merged.pop("sponsorblock-remove", None)
    if cli_settings.get("live") is False:
        for key in ("live-from-start", "wait-for-video", "write-live-chat"):
            merged.pop(key, None)
    if cli_settings.get("_whole-item") is True:
        merged.pop("chapter-sections", None)
        merged.pop("time-ranges", None)
    merged.update({key: value for key, value in cli_settings.items() if key != "_whole-item"})
    if merged.get("wait-for-video") is None:
        merged.pop("wait-for-video", None)
    return merged


def resolve_parameter_settings(
    profile: ParameterProfile | None,
    cli_settings: dict[str, object],
) -> ResolvedParameterSettings:
    """Merge settings and retain deterministic provenance for explanation."""
    settings = merge_parameter_settings(profile, cli_settings)
    sources: dict[str, str] = {}
    if profile is not None:
        sources.update({key: f"parameter profile {profile.name!r}" for key in profile.settings})
    sources.update({key: "explicit CLI" for key in cli_settings if key in settings})
    sources = {key: source for key, source in sources.items() if key in settings}
    return ResolvedParameterSettings(settings=settings, sources=sources)


def generated_profile_settings(
    source: ParameterProfile | None,
    cli_settings: dict[str, object],
) -> dict[str, object]:
    """Build settings for profile generation without snapshotting built-in defaults."""
    generated = merge_parameter_settings(source, cli_settings)
    if not generated:
        raise ValueError(
            "--generate-profile has no profile-eligible settings to save; "
            "supply options such as --resolution or select a source parameter profile"
        )
    return generated


def profile_document(name: str, settings: dict[str, object]) -> dict[str, object]:
    """Return a complete standalone defaults document for one generated profile."""
    validate_parameter_profile_name(name)
    validate_parameter_settings(settings, profile_name=name)
    return {
        "version": PARAMETER_PROFILE_VERSION,
        "profiles": {name: settings},
    }


def format_profile_document(name: str, settings: dict[str, object]) -> str:
    """Serialise one generated profile deterministically for stdout or a new file."""
    return json.dumps(profile_document(name, settings), indent=2, ensure_ascii=False) + "\n"


def write_parameter_profile(
    path: Path,
    name: str,
    settings: dict[str, object],
    *,
    overwrite: bool,
) -> None:
    """Atomically add or explicitly replace one profile in a defaults JSON file."""
    validate_parameter_profile_name(name)
    validate_parameter_settings(settings, profile_name=name)

    if path.is_file():
        profiles = load_parameter_profiles(path, allow_missing=False)
        if name in profiles and not overwrite:
            raise ValueError(
                f"parameter profile {name!r} already exists in {path}; use --overwrite-profile to replace it explicitly"
            )
        raw_profiles: dict[str, object] = {profile.name: dict(profile.settings) for profile in profiles.values()}
    else:
        raw_profiles = {}

    raw_profiles[name] = settings
    payload = {
        "version": PARAMETER_PROFILE_VERSION,
        "profiles": raw_profiles,
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(f"unable to write defaults file {path}: {exc}") from exc


def resolve_parameter_policy(
    settings: dict[str, object],
) -> tuple[DownloadPolicy, Path | None, str | None]:
    """Resolve merged profile settings into Downloader runtime policy."""
    min_resolution = int(settings["min-resolution"]) if "min-resolution" in settings else None
    max_resolution = int(settings["max-resolution"]) if "max-resolution" in settings else None
    min_fps = int(settings["min-fps"]) if "min-fps" in settings else None
    max_fps = int(settings["max-fps"]) if "max-fps" in settings else None
    if min_resolution is not None and max_resolution is not None and min_resolution > max_resolution:
        raise ValueError("min-resolution cannot be greater than max-resolution")
    if min_fps is not None and max_fps is not None and min_fps > max_fps:
        raise ValueError("min-fps cannot be greater than max-fps")
    if "format" in settings and any(key in settings for key in HARD_FORMAT_CONSTRAINT_KEYS):
        raise ValueError(
            "raw format selection cannot be combined with hard declarative format constraints; "
            "remove --format or the min/max resolution/FPS constraint"
        )

    audio_requested = bool(settings.get("audio-only", False)) or "audio-format" in settings
    audio_source_requested = any(key in settings for key in {"audio-source-codec", "audio-source-container"})
    if audio_source_requested and not audio_requested:
        raise ValueError("audio source codec/container constraints require --audio-only or --audio-format")
    if "audio-source-fallback" in settings and not audio_requested:
        raise ValueError("audio-source-fallback requires --audio-only or --audio-format")
    if "audio-quality" in settings and "audio-format" not in settings:
        raise ValueError("audio-quality requires audio-format because source-only audio does not transcode")
    if audio_requested and "format" in settings:
        raise ValueError("audio workflow options cannot be combined with a raw --format selector")
    video_only_keys = {
        "min-resolution",
        "max-resolution",
        "min-fps",
        "max-fps",
        "preferred-fps",
        "preferred-video-codec",
        "preferred-hdr",
        "merge-container",
    }
    conflicting_video_keys = sorted(video_only_keys & set(settings)) if audio_requested else []
    if conflicting_video_keys:
        rendered = ", ".join(conflicting_video_keys)
        raise ValueError(f"audio workflows cannot combine video-only settings: {rendered}")
    if audio_requested and bool(settings.get("embed-subs", False)):
        raise ValueError("audio workflows cannot embed subtitles into an audio-only primary output")

    resolution = validate_resolution(str(settings.get("resolution", DEFAULT_RESOLUTION)))
    format_selector = str(settings.get("format", FORMAT_SELECTOR))
    reverse_playlist = bool(settings.get("reverse-playlist", False))
    playlist_value = settings.get("playlist")
    playlist = playlist_value if isinstance(playlist_value, bool) else None
    playlist_items = tuple(settings.get("playlist-items", ()))
    if playlist_items and playlist is False:
        raise ValueError("playlist item selection cannot be combined with --no-playlist")

    live = bool(settings.get("live", False))
    live_from_start = bool(settings.get("live-from-start", False))
    wait_for_video = str(settings["wait-for-video"]) if "wait-for-video" in settings else None
    write_live_chat = bool(settings.get("write-live-chat", False))
    chapter_sections = tuple(settings.get("chapter-sections", ()))
    time_ranges = tuple(settings.get("time-ranges", ()))
    partial_media = bool(chapter_sections or time_ranges)
    if partial_media and live:
        raise ValueError("partial-media selection cannot be combined with live mode")
    if (live_from_start or wait_for_video is not None or write_live_chat) and not live:
        raise ValueError("live-from-start, wait-for-video and write-live-chat require explicit live mode")

    cookies_from_browser = None
    if "cookies" in settings:
        cookie_path = Path(str(settings["cookies"])).expanduser()
        cookies_file = resolve_cookies(cookie_path, disabled=False)
    elif "cookies-from-browser" in settings:
        cookies_file = None
        cookies_from_browser = str(settings["cookies-from-browser"])
    else:
        disabled = bool(settings.get("no-cookies", False))
        cookies_file = resolve_cookies(None, disabled=disabled)

    return (
        DownloadPolicy(
            resolution=resolution,
            format_selector=format_selector,
            reverse_playlist=reverse_playlist,
            playlist=playlist,
            playlist_items=playlist_items,
            live=live,
            live_from_start=live_from_start,
            wait_for_video=wait_for_video,
            write_live_chat=write_live_chat,
            chapter_sections=chapter_sections,
            time_ranges=time_ranges,
            limit_rate=str(settings.get("limit-rate", DEFAULT_DOWNLOAD_RATE)),
            throttled_rate=(str(settings["throttled-rate"]) if "throttled-rate" in settings else None),
            concurrent_fragments=(
                int(settings["concurrent-fragments"]) if "concurrent-fragments" in settings else None
            ),
            retries=(str(settings["retries"]) if "retries" in settings else None),
            fragment_retries=(str(settings["fragment-retries"]) if "fragment-retries" in settings else None),
            file_access_retries=(str(settings["file-access-retries"]) if "file-access-retries" in settings else None),
            extractor_retries=(str(settings["extractor-retries"]) if "extractor-retries" in settings else None),
            retry_sleep=tuple(settings.get("retry-sleep", ())),
            archive_file=Path(str(settings.get("archive", ARCHIVE_FILE))).expanduser(),
            temp_path=Path(str(settings.get("temp-path", TEMP_DIR))).expanduser(),
            extractor_args=tuple(settings.get("extractor-args", DEFAULT_EXTRACTOR_ARGS)),
            min_resolution=min_resolution,
            max_resolution=max_resolution,
            min_fps=min_fps,
            max_fps=max_fps,
            preferred_fps=(int(settings["preferred-fps"]) if "preferred-fps" in settings else None),
            preferred_video_codec=(
                str(settings["preferred-video-codec"]) if "preferred-video-codec" in settings else None
            ),
            preferred_audio_codec=(
                str(settings["preferred-audio-codec"]) if "preferred-audio-codec" in settings else None
            ),
            preferred_hdr=(str(settings["preferred-hdr"]) if "preferred-hdr" in settings else None),
            preferred_audio_channels=(
                int(settings["preferred-audio-channels"]) if "preferred-audio-channels" in settings else None
            ),
            merge_container=(str(settings["merge-container"]) if "merge-container" in settings else None),
            audio_only=bool(settings.get("audio-only", False)),
            audio_source_codec=(str(settings["audio-source-codec"]) if "audio-source-codec" in settings else None),
            audio_source_container=(
                str(settings["audio-source-container"]) if "audio-source-container" in settings else None
            ),
            audio_source_fallback=bool(settings.get("audio-source-fallback", True)),
            audio_format=(str(settings["audio-format"]) if "audio-format" in settings else None),
            audio_quality=(str(settings["audio-quality"]) if "audio-quality" in settings else None),
            write_subtitles=bool(settings.get("write-subs", False)),
            write_auto_subtitles=bool(settings.get("write-auto-subs", False)),
            subtitle_languages=(str(settings["sub-langs"]) if "sub-langs" in settings else None),
            subtitle_format=(str(settings["sub-format"]) if "sub-format" in settings else None),
            embed_subtitles=bool(settings.get("embed-subs", False)),
            write_thumbnail=bool(settings.get("write-thumbnail", False)),
            embed_thumbnail=bool(settings.get("embed-thumbnail", False)),
            write_info_json=bool(settings.get("write-info-json", False)),
            embed_metadata=bool(settings.get("embed-metadata", True)),
            embed_chapters=bool(settings.get("embed-chapters", True)),
            sponsorblock=bool(settings.get("sponsorblock", True)),
            sponsorblock_mark=(str(settings["sponsorblock-mark"]) if "sponsorblock-mark" in settings else None),
            sponsorblock_remove=(
                str(settings["sponsorblock-remove"])
                if "sponsorblock-remove" in settings
                else DEFAULT_SPONSORBLOCK_REMOVE
            ),
        ),
        cookies_file,
        cookies_from_browser,
    )


def remove_completed_id(path: Path, video_id: str) -> bool:
    """Atomically remove exact ``video_id`` lines from an input file.

    The rewrite is fsynchronised and replaced atomically so a power loss or
    process interruption cannot leave a partially rewritten ID file. Only lines
    whose stripped content exactly equals the completed video ID are removed;
    comments, blank lines, URLs and unrelated text are preserved byte-for-byte.
    """
    resolved = path.expanduser().resolve()
    try:
        original = resolved.read_bytes()
        metadata = resolved.stat()
    except OSError as exc:
        raise RuntimeError(f"unable to read completed-ID input file {resolved}: {exc}") from exc

    target = video_id.encode("utf-8")
    lines = original.splitlines(keepends=True)
    retained = [line for line in lines if line.strip() != target]
    if len(retained) == len(lines):
        return False

    replacement = b"".join(retained)
    temporary = resolved.with_name(f".{resolved.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(replacement)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, metadata.st_mode)
        os.replace(temporary, resolved)
        try:
            directory_fd = os.open(resolved.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"unable to update completed-ID input file {resolved}: {exc}") from exc

    return True


def archived_video_ids(path: Path) -> set[str]:
    """Return video IDs recorded in yt-dlp's configured download archive.

    yt-dlp archive records consist of an extractor identifier followed by the
    extractor-specific video ID. Malformed or blank records are ignored rather
    than being treated as evidence of successful completion.
    """
    if not path.is_file():
        return set()

    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"unable to read download archive {path}: {exc}") from exc

    completed: set[str] = set()
    for line in lines:
        fields = line.strip().split()
        if len(fields) >= 2:
            completed.add(fields[-1])
    return completed


def remove_archived_ids(input_file: Path, archive_file: Path) -> int:
    """Remove exact input IDs already proven complete by the download archive.

    Reconciliation happens before yt-dlp starts. This makes an existing queue
    immediately reflect prior successful work and avoids repeatedly feeding
    archive hits back to yt-dlp. Each removal uses the same atomic rewrite path
    as the per-video ``after_move`` completion callback.
    """
    removed = 0
    for video_id in archived_video_ids(archive_file):
        if remove_completed_id(input_file, video_id):
            removed += 1
    return removed


def completion_exec_command(input_file: Path) -> str:
    """Return the yt-dlp ``after_move`` callback used for durable ID removal."""
    command = [
        shlex.quote(sys.executable),
        shlex.quote(str(Path(__file__).resolve())),
        "--_remove-completed-id",
        shlex.quote(str(input_file.expanduser().resolve())),
        "%(id)q",
    ]
    return " ".join(command)


def output_record_exec_command(event_file: Path) -> str:
    """Return an ``after_move`` callback that records one completed primary output."""
    command = [
        shlex.quote(sys.executable),
        shlex.quote(str(Path(__file__).resolve())),
        "--_record-output",
        shlex.quote(str(event_file.expanduser().resolve())),
        "%(id)q",
        "%(filepath)q",
    ]
    return " ".join(command)


def append_output_record(event_file: Path, media_id: str, output_path: str) -> None:
    """Durably append one completed-media event for later manifest construction."""
    resolved = event_file.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    record = (json.dumps({"id": media_id, "path": output_path}, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        descriptor = os.open(resolved, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "ab") as handle:
            handle.write(record)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RuntimeError(f"unable to record completed output {output_path}: {exc}") from exc


def validate_remove_completed_ids(args: argparse.Namespace, input_source: InputSource) -> None:
    """Validate queue mutation and reporting options as one coherent mode."""
    queue_outputs_requested = (
        getattr(args, "queue_report", None) is not None or getattr(args, "failed_targets", None) is not None
    )
    if queue_outputs_requested and not args.remove_completed_ids:
        raise ValueError("--queue-report and --failed-targets require --remove-completed-ids")
    if not args.remove_completed_ids:
        return
    if input_source.batch_file is None:
        raise ValueError(
            "--remove-completed-ids requires file input; use --input-file FILE, "
            "a positional batch file, or the default ./ids.txt"
        )


def queue_targets(path: Path) -> tuple[str, ...]:
    """Return meaningful batch-file target lines in stable first-seen order."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"unable to read queue file {path}: {exc}") from exc

    targets: list[str] = []
    seen: set[str] = set()
    for line in lines:
        target = line.strip()
        if not target or target.startswith("#") or target in seen:
            continue
        targets.append(target)
        seen.add(target)
    return tuple(targets)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Durably replace ``path`` with ``content`` using the queue rewrite discipline."""
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f".{resolved.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        try:
            directory_fd = os.open(resolved.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"unable to write {resolved}: {exc}") from exc


def queue_run_report(
    *,
    queue_file: Path,
    archive_file: Path,
    requested: Sequence[str],
    archived_before: set[str],
    remaining: Sequence[str],
    exit_status: int,
) -> dict[str, object]:
    """Build a conservative queue outcome report from durable observable state."""
    requested_set = set(requested)
    remaining_set = set(remaining)
    already_archived = [target for target in requested if target in archived_before]
    completed = [target for target in requested if target not in archived_before and target not in remaining_set]
    unresolved = [target for target in requested if target in remaining_set]
    return {
        "kind": "yt-download-queue-report",
        "version": PROGRAM_VERSION,
        "queue_file": str(queue_file.expanduser().resolve()),
        "archive_file": str(archive_file.expanduser().resolve()),
        "exit_status": exit_status,
        "interrupted": exit_status == 130,
        "counts": {
            "requested": len(requested_set),
            "already_archived": len(already_archived),
            "completed": len(completed),
            "unresolved": len(unresolved),
        },
        "targets": {
            "requested": list(requested),
            "already_archived": already_archived,
            "completed": completed,
            "unresolved": unresolved,
        },
    }


def write_queue_report(path: Path, report: dict[str, object]) -> None:
    """Atomically write a deterministic UTF-8 JSON queue report."""
    content = (json.dumps(report, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def write_failed_targets(path: Path, targets: Sequence[str]) -> None:
    """Atomically write unresolved targets as a reusable newline-delimited batch file."""
    content = "".join(f"{target}\n" for target in targets).encode("utf-8")
    atomic_write_bytes(path, content)


def utc_timestamp() -> str:
    """Return the current UTC time in a stable ISO 8601 representation."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_output_records(event_file: Path) -> tuple[dict[str, str], ...]:
    """Read unique completed primary-output events from an internal event ledger."""
    if not event_file.is_file():
        return ()
    try:
        lines = event_file.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"unable to read output event ledger {event_file}: {exc}") from exc
    outputs: list[dict[str, str]] = []
    seen: set[tuple[str, Path]] = set()
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid output event ledger record: {exc}") from exc
        media_id = payload.get("id") if isinstance(payload, dict) else None
        value = payload.get("path") if isinstance(payload, dict) else None
        if not isinstance(media_id, str) or not media_id:
            raise RuntimeError("invalid output event ledger record: missing media ID")
        if not isinstance(value, str) or not value:
            raise RuntimeError("invalid output event ledger record: missing path")
        path = Path(value).expanduser().resolve()
        key = (media_id, path)
        if key not in seen:
            outputs.append({"id": media_id, "path": str(path)})
            seen.add(key)
    return tuple(outputs)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one completed output file."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise RuntimeError(f"unable to hash completed output {path}: {exc}") from exc
    return digest.hexdigest()


def output_manifest_entries(records: Sequence[dict[str, str]], *, hash_outputs: bool) -> list[dict[str, object]]:
    """Describe completed primary outputs and optionally calculate SHA-256 hashes."""
    entries: list[dict[str, object]] = []
    for record in records:
        path = Path(record["path"])
        exists = path.is_file()
        entry: dict[str, object] = {"id": record["id"], "path": str(path), "exists": exists}
        if exists:
            try:
                entry["size_bytes"] = path.stat().st_size
            except OSError as exc:
                raise RuntimeError(f"unable to inspect completed output {path}: {exc}") from exc
            if hash_outputs:
                entry["sha256"] = sha256_file(path)
        elif hash_outputs:
            entry["sha256"] = None
        entries.append(entry)
    return entries


def yt_dlp_version(executable: str) -> str | None:
    """Return the invoked yt-dlp version without making manifest creation depend on it."""
    try:
        completed = subprocess.run(
            [executable, "--version"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    version = completed.stdout.strip()
    return version or None


def manifest_input_targets(input_source: InputSource) -> list[str] | None:
    """Return known input targets without consuming standard input."""
    if input_source.batch_file is not None:
        return list(queue_targets(input_source.batch_file))
    if input_source.stdin:
        return None
    return list(input_source.direct_targets)


def run_manifest_payload(
    *,
    plan: DownloadPlan,
    yt_dlp_version_value: str | None,
    started_at: str,
    ended_at: str,
    exit_status: int,
    targets: list[str] | None,
    outputs: list[dict[str, object]],
    queue_report: dict[str, object] | None,
    hash_outputs: bool,
) -> dict[str, object]:
    """Build a redacted operational manifest from authoritative run state."""
    return {
        "kind": "yt-download-run-manifest",
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "downloader": {"version": PROGRAM_VERSION},
        "yt_dlp": {
            "version": yt_dlp_version_value,
            "exit_status": exit_status,
        },
        "run": {
            "started_at": started_at,
            "ended_at": ended_at,
            "interrupted": exit_status == 130,
        },
        "input": {
            "targets": targets,
            "targets_known": targets is not None,
            "derivative_partial_media": plan.policy.partial_media,
        },
        "resolved_plan": explain_plan_payload(plan),
        "queue": queue_report,
        "outputs": {
            "primary": outputs,
            "associated_artefacts": {
                "actual_paths_tracked": False,
                "requested_policy": {
                    "write_subtitles": plan.policy.write_subtitles,
                    "write_auto_subtitles": plan.policy.write_auto_subtitles,
                    "write_thumbnail": plan.policy.write_thumbnail,
                    "write_info_json": plan.policy.write_info_json,
                },
            },
        },
        "integrity": {
            "sha256_requested": hash_outputs,
            "scope": "completed primary outputs recorded at yt-dlp after_move",
            "meaning": "ordinary integrity verification only; not proof of authenticity or provenance",
        },
    }


def write_run_manifest(path: Path, manifest: dict[str, object]) -> None:
    """Atomically write a deterministic UTF-8 JSON run manifest."""
    content = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    atomic_write_bytes(path, content)


def validate_environment(*, dry_run: bool) -> str:
    """Validate external executable requirements and return the yt-dlp command name."""
    executable = shutil.which("yt-dlp")
    if executable is None:
        if dry_run:
            executable = "yt-dlp"
        else:
            raise RuntimeError("yt-dlp was not found on PATH")
    return executable


def resolve_cookies(requested: Path | None, *, disabled: bool) -> Path | None:
    """Resolve the cookie policy for one invocation.

    Explicitly requested cookie files are validated strictly. Without an explicit
    request, the script-local cookies.txt is used only when it exists.
    """
    if disabled:
        return None
    if requested is not None:
        path = requested.expanduser()
        if not path.is_file():
            raise ValueError(f"cookies file not found: {path}")
        return path
    if COOKIES_FILE.is_file():
        return COOKIES_FILE
    return None


def describe_cookie_source(settings: dict[str, object], cookies_file: Path | None) -> str:
    """Return a stable human-readable description of the resolved cookie policy."""
    if "cookies" in settings:
        return "explicit cookie file"
    if "cookies-from-browser" in settings:
        return "browser cookies"
    if bool(settings.get("no-cookies", False)):
        return "disabled"
    if cookies_file is not None:
        return "automatic script-local cookies.txt"
    return "none available"


def create_download_plan(
    *,
    executable: str,
    resolved_parameters: ResolvedParameterSettings,
    input_source: InputSource,
    output_profile: OutputProfile | None,
    defaults_file: Path,
    parameter_profile: ParameterProfile | None,
    remove_completed_ids: bool,
) -> DownloadPlan:
    """Resolve one complete download plan without mutating queues or launching yt-dlp."""
    policy, cookies_file, cookies_from_browser = resolve_parameter_policy(resolved_parameters.settings)
    if remove_completed_ids and policy.playlist_items:
        raise ValueError(
            "playlist item selection cannot be combined with --remove-completed-ids; "
            "queue removal tracks completed target IDs, not completion of a playlist container target"
        )
    if remove_completed_ids and policy.partial_media:
        raise ValueError(
            "partial-media selection cannot be combined with --remove-completed-ids; "
            "a derivative section does not establish completion of the source target"
        )
    return DownloadPlan(
        executable=executable,
        policy=policy,
        input_source=input_source,
        output_profile=output_profile,
        cookies_file=cookies_file,
        cookies_from_browser=cookies_from_browser,
        cookies_source=describe_cookie_source(resolved_parameters.settings, cookies_file),
        remove_completed_ids=remove_completed_ids,
        defaults_file=defaults_file,
        parameter_profile=parameter_profile,
        parameter_sources=dict(resolved_parameters.sources),
    )


SENSITIVE_EXTRACTOR_ARGUMENT_NAMES = frozenset(
    {
        "api_key",
        "app_info",
        "authorization",
        "client_id",
        "credential",
        "data_sync_id",
        "device_id",
        "hls_key",
        "innertube_key",
        "password",
        "po_token",
        "refresh_token",
        "secret",
        "token",
        "visitor_data",
    }
)


def redact_extractor_argument(value: str) -> str:
    """Redact likely credentials from one yt-dlp extractor-argument string."""
    if ":" not in value:
        return value
    extractor, argument_text = value.split(":", 1)
    redacted: list[str] = []
    for clause in argument_text.split(";"):
        name, separator, raw_value = clause.partition("=")
        normalised = name.strip().lower().replace("-", "_")
        if separator and (
            normalised in SENSITIVE_EXTRACTOR_ARGUMENT_NAMES
            or any(marker in normalised for marker in ("token", "password", "secret", "credential"))
        ):
            redacted.append(f"{name}=<redacted>")
        else:
            redacted.append(clause)
    return f"{extractor}:{';'.join(redacted)}"


def redact_command(command: Sequence[str]) -> list[str]:
    """Return a diagnostic command with sensitive extractor-argument values removed."""
    result = list(command)
    for index, item in enumerate(result[:-1]):
        if item == "--extractor-args":
            result[index + 1] = redact_extractor_argument(result[index + 1])
    return result


def _input_source_payload(source: InputSource) -> dict[str, object]:
    """Return a serialisable description of one resolved input source."""
    if source.batch_file is not None:
        return {"kind": "batch-file", "path": str(source.batch_file)}
    if source.stdin:
        return {"kind": "stdin"}
    return {"kind": "direct", "targets": list(source.direct_targets)}


def explain_plan_payload(plan: DownloadPlan) -> dict[str, object]:
    """Return the stable machine-readable representation of a resolved plan."""
    output_profile = None
    if plan.output_profile is not None:
        output_profile = {
            "source": str(plan.output_profile.source),
            "path": plan.output_profile.path,
            "output": plan.output_profile.output,
        }
    return {
        "kind": "yt-download-plan",
        "schema_version": PLAN_SCHEMA_VERSION,
        "version": PROGRAM_VERSION,
        "parameter_profile": {
            "name": plan.parameter_profile.name if plan.parameter_profile is not None else None,
            "source": str(plan.parameter_profile.source) if plan.parameter_profile is not None else None,
            "defaults_file": str(plan.defaults_file),
        },
        "parameter_sources": dict(sorted(plan.parameter_sources.items())),
        "policy": {
            "resolution": plan.policy.resolution,
            "format": plan.policy.effective_format_selector,
            "raw_format": plan.policy.format_selector,
            "format_sort": plan.policy.sort_selector,
            "min_resolution": plan.policy.min_resolution,
            "max_resolution": plan.policy.max_resolution,
            "min_fps": plan.policy.min_fps,
            "max_fps": plan.policy.max_fps,
            "preferred_fps": plan.policy.preferred_fps,
            "preferred_video_codec": plan.policy.preferred_video_codec,
            "preferred_audio_codec": plan.policy.preferred_audio_codec,
            "preferred_hdr": plan.policy.preferred_hdr,
            "preferred_audio_channels": plan.policy.preferred_audio_channels,
            "merge_container": plan.policy.merge_container,
            "audio_only": plan.policy.audio_only,
            "audio_source_codec": plan.policy.audio_source_codec,
            "audio_source_container": plan.policy.audio_source_container,
            "audio_source_fallback": plan.policy.audio_source_fallback,
            "audio_format": plan.policy.audio_format,
            "audio_quality": plan.policy.audio_quality,
            "audio_conversion": plan.policy.audio_format is not None,
            "write_subtitles": plan.policy.write_subtitles,
            "write_auto_subtitles": plan.policy.write_auto_subtitles,
            "subtitle_languages": plan.policy.subtitle_languages,
            "subtitle_format": plan.policy.subtitle_format,
            "embed_subtitles": plan.policy.embed_subtitles,
            "write_thumbnail": plan.policy.write_thumbnail,
            "embed_thumbnail": plan.policy.embed_thumbnail,
            "write_info_json": plan.policy.write_info_json,
            "embed_metadata": plan.policy.embed_metadata,
            "embed_chapters": plan.policy.embed_chapters,
            "sponsorblock": plan.policy.sponsorblock,
            "sponsorblock_mark": plan.policy.sponsorblock_mark,
            "sponsorblock_remove": plan.policy.sponsorblock_remove,
            "reverse_playlist": plan.policy.reverse_playlist,
            "playlist": plan.policy.playlist,
            "playlist_items": list(plan.policy.playlist_items),
            "playlist_item_spec": plan.policy.playlist_item_spec,
            "live": plan.policy.live,
            "live_from_start": plan.policy.live_from_start,
            "wait_for_video": plan.policy.wait_for_video,
            "write_live_chat": plan.policy.write_live_chat,
            "partial_media": plan.policy.partial_media,
            "chapter_sections": list(plan.policy.chapter_sections),
            "time_ranges": list(plan.policy.time_ranges),
            "download_sections": list(plan.policy.download_sections),
            "limit_rate": plan.policy.limit_rate,
            "throttled_rate": plan.policy.throttled_rate,
            "concurrent_fragments": plan.policy.concurrent_fragments,
            "retries": plan.policy.retries,
            "fragment_retries": plan.policy.fragment_retries,
            "file_access_retries": plan.policy.file_access_retries,
            "extractor_retries": plan.policy.extractor_retries,
            "retry_sleep": list(plan.policy.retry_sleep),
            "extractor_args": [redact_extractor_argument(value) for value in plan.policy.extractor_args],
        },
        "authentication": {
            "source": plan.cookies_source,
            "cookies_file": str(plan.cookies_file) if plan.cookies_file is not None else None,
            "cookies_from_browser": plan.cookies_from_browser,
        },
        "input": _input_source_payload(plan.input_source),
        "output_profile": output_profile,
        "paths": {
            "archive": str(plan.policy.archive_file),
            "archive_enabled": not plan.policy.partial_media,
            "temporary": str(plan.policy.temp_path),
        },
        "queue": {
            "remove_completed_ids": plan.remove_completed_ids,
            "archive_reconciliation": bool(plan.remove_completed_ids and plan.input_source.batch_file is not None),
        },
        "yt_dlp": {
            "executable": plan.executable,
            "command": redact_command(plan.command()),
        },
    }


def format_plan_explanation(plan: DownloadPlan) -> str:
    """Return a concise human-readable explanation of a resolved download plan."""
    payload = explain_plan_payload(plan)
    profile = payload["parameter_profile"]
    policy = payload["policy"]
    authentication = payload["authentication"]
    input_payload = payload["input"]
    output_profile = payload["output_profile"]
    queue = payload["queue"]

    parameter_name = profile["name"] if isinstance(profile, dict) else None
    if parameter_name is None:
        parameter_text = "none"
    else:
        parameter_text = f"{parameter_name} ({profile['source']})"

    if isinstance(output_profile, dict):
        output_text = str(output_profile["source"])
    else:
        output_text = "yt-dlp native defaults"

    if isinstance(input_payload, dict) and input_payload.get("kind") == "batch-file":
        input_text = f"batch file {input_payload['path']}"
    elif isinstance(input_payload, dict) and input_payload.get("kind") == "stdin":
        input_text = "standard input"
    else:
        targets = input_payload.get("targets", []) if isinstance(input_payload, dict) else []
        input_text = f"{len(targets)} direct target(s)"

    lines = [
        f"{PROGRAM_NAME} {PROGRAM_VERSION} resolved download plan",
        "",
        f"Parameter profile: {parameter_text}",
        f"Defaults file:     {plan.defaults_file}",
        f"Output profile:    {output_text}",
        f"Input:             {input_text}",
        f"Resolution:        {policy['resolution']}",
        f"Format selector:   {policy['format']}",
        f"Format sort:       {policy['format_sort']}",
        f"Resolution bounds: {policy['min_resolution'] or 'none'}..{policy['max_resolution'] or 'none'}",
        f"FPS bounds:        {policy['min_fps'] or 'none'}..{policy['max_fps'] or 'none'}",
        f"Preferred FPS:     {policy['preferred_fps'] or 'yt-dlp default'}",
        f"Video codec:       {policy['preferred_video_codec'] or 'yt-dlp default'}",
        f"Audio codec:       {policy['preferred_audio_codec'] or 'yt-dlp default'}",
        f"HDR preference:    {policy['preferred_hdr'] or 'yt-dlp default'}",
        f"Audio channels:    {policy['preferred_audio_channels'] or 'yt-dlp default'}",
        f"Merge container:   {policy['merge_container'] or 'yt-dlp default'}",
        f"Audio only:        {policy['audio_only'] or policy['audio_conversion']}",
        f"Audio source codec:{' ' if policy['audio_source_codec'] else '  '}{policy['audio_source_codec'] or 'any'}",
        f"Audio source ext:  {policy['audio_source_container'] or 'any'}",
        f"Audio fallback:    {policy['audio_source_fallback']}",
        f"Audio conversion:  {policy['audio_format'] or 'disabled'}",
        f"Audio quality:     {policy['audio_quality'] or 'yt-dlp default'}",
        f"Manual subtitles:  {policy['write_subtitles']}",
        f"Auto subtitles:    {policy['write_auto_subtitles']}",
        f"Subtitle langs:    {policy['subtitle_languages'] or 'yt-dlp default'}",
        f"Subtitle format:   {policy['subtitle_format'] or 'yt-dlp default'}",
        f"Embed subtitles:   {policy['embed_subtitles']}",
        f"Write thumbnail:   {policy['write_thumbnail']}",
        f"Embed thumbnail:   {policy['embed_thumbnail']}",
        f"Write info JSON:   {policy['write_info_json']}",
        f"Embed metadata:    {policy['embed_metadata']}",
        f"Embed chapters:    {policy['embed_chapters']}",
        f"SponsorBlock:      {policy['sponsorblock']}",
        f"SponsorBlock mark: {policy['sponsorblock_mark'] or 'none'}",
        f"SponsorBlock cut:  {policy['sponsorblock_remove'] or 'none'}",
        f"Playlist:          {policy['playlist'] if policy['playlist'] is not None else 'yt-dlp default'}",
        f"Playlist items:    {policy['playlist_item_spec'] or 'all'}",
        f"Reverse playlist:  {policy['reverse_playlist']}",
        f"Partial media:     {policy['partial_media']}",
        f"Chapter sections:  {', '.join(policy['chapter_sections']) if policy['chapter_sections'] else 'none'}",
        f"Time ranges:       {', '.join(policy['time_ranges']) if policy['time_ranges'] else 'none'}",
        f"Cookies:           {authentication['source']}"
        + (f" ({authentication['cookies_file']})" if authentication["cookies_file"] else "")
        + (f" ({authentication['cookies_from_browser']})" if authentication["cookies_from_browser"] else ""),
        f"Limit rate:        {policy['limit_rate']}",
        f"Throttled rate:    {policy['throttled_rate'] or 'yt-dlp default'}",
        f"Concurrent frags:  {policy['concurrent_fragments'] or 'yt-dlp default'}",
        f"Retries:           {policy['retries'] or 'yt-dlp default'}",
        f"Fragment retries:  {policy['fragment_retries'] or 'yt-dlp default'}",
        f"File retries:      {policy['file_access_retries'] or 'yt-dlp default'}",
        f"Extractor retries: {policy['extractor_retries'] or 'yt-dlp default'}",
        f"Archive:           {plan.policy.archive_file}",
        f"Temporary path:    {plan.policy.temp_path}",
        f"Queue removal:     {queue['remove_completed_ids']}",
        "",
        "Resolved yt-dlp command:",
        f"  {format_command(payload['yt_dlp']['command'])}",
    ]
    if plan.parameter_sources:
        lines.extend(["", "Parameter value sources:"])
        for key, source in sorted(plan.parameter_sources.items()):
            lines.append(f"  {key}: {source}")
    return "\n".join(lines)


def build_yt_dlp_command(
    executable: str,
    policy: DownloadPolicy,
    input_source: InputSource,
    profile: OutputProfile | None,
    *,
    cookies_file: Path | None = None,
    cookies_from_browser: str | None = None,
    remove_completed_ids: bool = False,
    output_event_file: Path | None = None,
) -> list[str]:
    """Build the complete yt-dlp command without invoking a shell."""
    command = [
        executable,
        "-f",
        policy.effective_format_selector,
        "-S",
        policy.sort_selector,
        "-r",
        policy.limit_rate,
        "--mtime",
    ]
    if policy.partial_media:
        command.append("--no-download-archive")
    else:
        command.extend(("--download-archive", str(policy.archive_file)))
    if not (policy.audio_only or policy.audio_format is not None):
        command.append("--video-multistreams")
    command.append("--audio-multistreams")

    if policy.audio_format is not None:
        command.extend(("--extract-audio", "--audio-format", policy.audio_format))
        if policy.audio_quality is not None:
            command.extend(("--audio-quality", policy.audio_quality))

    if policy.write_subtitles or policy.write_live_chat:
        command.append("--write-subs")
    if policy.write_auto_subtitles:
        command.append("--write-auto-subs")
    subtitle_languages = policy.subtitle_languages
    if policy.write_live_chat:
        if subtitle_languages is None:
            subtitle_languages = "live_chat"
        else:
            requested = [item.strip() for item in subtitle_languages.split(",")]
            if "-live_chat" in requested:
                raise ValueError("write-live-chat cannot be combined with a sub-langs exclusion for live_chat")
            if "live_chat" not in requested:
                subtitle_languages = f"{subtitle_languages},live_chat"
    if subtitle_languages is not None:
        command.extend(("--sub-langs", subtitle_languages))
    if policy.subtitle_format is not None:
        command.extend(("--sub-format", policy.subtitle_format))
    if policy.embed_subtitles:
        command.append("--embed-subs")
    if policy.write_thumbnail:
        command.append("--write-thumbnail")
    if policy.embed_thumbnail:
        command.append("--embed-thumbnail")
    if policy.write_info_json:
        command.append("--write-info-json")
    command.append("--embed-metadata" if policy.embed_metadata else "--no-embed-metadata")
    command.append("--embed-chapters" if policy.embed_chapters else "--no-embed-chapters")
    if policy.sponsorblock:
        if policy.sponsorblock_mark is not None:
            command.extend(("--sponsorblock-mark", policy.sponsorblock_mark))
        if policy.sponsorblock_remove is not None:
            command.extend(("--sponsorblock-remove", policy.sponsorblock_remove))
    else:
        command.append("--no-sponsorblock")

    if policy.merge_container is not None:
        command.extend(("--merge-output-format", policy.merge_container))
    if policy.throttled_rate is not None:
        command.extend(("--throttled-rate", policy.throttled_rate))
    if policy.concurrent_fragments is not None:
        command.extend(("--concurrent-fragments", str(policy.concurrent_fragments)))
    for option, value in (
        ("--retries", policy.retries),
        ("--fragment-retries", policy.fragment_retries),
        ("--file-access-retries", policy.file_access_retries),
        ("--extractor-retries", policy.extractor_retries),
    ):
        if value is not None:
            command.extend((option, value))
    for expression in policy.retry_sleep:
        command.extend(("--retry-sleep", expression))

    if cookies_file is not None:
        command.extend(("--cookies", str(cookies_file)))
    elif cookies_from_browser is not None:
        command.extend(("--cookies-from-browser", cookies_from_browser))

    if profile is not None:
        if profile.output is not None and not policy.partial_media:
            command.extend(("--output", profile.output))
        if profile.path is not None:
            command.extend(("--paths", f"home:{profile.path}"))

    if policy.partial_media:
        command.extend(
            (
                "--output",
                "%(title)s [%(id)s] [section %(section_number)03d - %(section_title)s].%(ext)s",
            )
        )

    command.extend(("--paths", f"temp:{policy.temp_path}"))
    for extractor_arg in policy.extractor_args:
        command.extend(("--extractor-args", extractor_arg))

    if policy.live_from_start:
        command.append("--live-from-start")
    elif policy.live:
        command.append("--no-live-from-start")
    if policy.wait_for_video is not None:
        command.extend(("--wait-for-video", policy.wait_for_video))
    elif policy.live:
        command.append("--no-wait-for-video")

    for expression in policy.download_sections:
        command.extend(("--download-sections", expression))

    if policy.playlist_item_spec is not None:
        command.extend(("-I", policy.playlist_item_spec))

    if policy.reverse_playlist:
        command.append("--playlist-reverse")

    if policy.playlist is True:
        command.append("--yes-playlist")
    elif policy.playlist is False:
        command.append("--no-playlist")

    if output_event_file is not None:
        command.extend(("--exec", f"after_move:{output_record_exec_command(output_event_file)}"))

    if remove_completed_ids:
        assert input_source.batch_file is not None
        command.extend(
            (
                "--exec",
                f"after_move:{completion_exec_command(input_source.batch_file)}",
            )
        )

    input_source.append_to(command)
    return command


def format_command(command: Sequence[str]) -> str:
    """Return a shell-readable representation of a command for diagnostics."""
    return shlex.join(command)


def run(command: Sequence[str], *, dry_run: bool) -> int:
    """Run yt-dlp and return its exit status."""
    if dry_run:
        print(format_command(command))
        return 0

    try:
        completed = subprocess.run(command, check=False)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"Error: unable to start yt-dlp: {exc}", file=sys.stderr)
        return 1

    return completed.returncode


def main(argv: Sequence[str] | None = None) -> int:
    """Parse arguments, construct the yt-dlp invocation, and execute it."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args._remove_completed_id is not None:
        input_file, video_id = args._remove_completed_id
        try:
            removed = remove_completed_id(Path(input_file), video_id)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if removed:
            print(f"Removed completed ID {video_id} from {input_file}", file=sys.stderr)
        return 0

    if args._record_output is not None:
        event_file, media_id, output_path = args._record_output
        try:
            append_output_record(Path(event_file), media_id, output_path)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.examples:
        show_examples(parser)
        return 0

    if args.schema_json:
        raw_args = list(sys.argv[1:] if argv is None else argv)
        if raw_args != ["--schema-json"]:
            parser.error("--schema-json must be used on its own")
        emit_machine_contract()
        return 0

    if args.capabilities or args.capabilities_json:
        raw_args = list(sys.argv[1:] if argv is None else argv)
        expected = ["--capabilities-json"] if args.capabilities_json else ["--capabilities"]
        if args.capabilities and args.capabilities_json:
            parser.error("--capabilities and --capabilities-json cannot be combined")
        if raw_args != expected:
            parser.error(f"{expected[0]} must be used on its own")
        payload = capabilities_payload()
        if args.capabilities_json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(format_capabilities(payload))
        return 0

    resolved_defaults = defaults_path(args.defaults)

    if args.validate_config is not None:
        raw_path = args.validate_config
        path = resolved_defaults if raw_path == "" else Path(raw_path)
        try:
            result = validate_config_file(path)
        except ValueError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    explicit_defaults = args.defaults is not None

    if args.list_parameters and args.generate_profile is not None:
        parser.error("--list-parameters cannot be combined with --generate-profile")
    if args.dry_run and (args.explain or args.explain_json):
        parser.error("--dry-run cannot be combined with --explain or --explain-json")
    if args.dry_run and (args.queue_report is not None or args.failed_targets is not None):
        parser.error("--queue-report and --failed-targets are unavailable with --dry-run")
    if args.dry_run and args.run_manifest is not None:
        parser.error("--run-manifest is unavailable with --dry-run")
    if (args.explain or args.explain_json) and args.run_manifest is not None:
        parser.error("--run-manifest is unavailable with --explain or --explain-json")
    if args.hash_outputs and args.run_manifest is None:
        parser.error("--hash-outputs requires --run-manifest FILE")
    if args.write_profile and args.generate_profile is None:
        parser.error("--write-profile requires --generate-profile NAME")
    if args.overwrite_profile and not args.write_profile:
        parser.error("--overwrite-profile requires --write-profile")

    if args.list_parameters:
        try:
            names = list_parameter_profiles(resolved_defaults, explicit_defaults=explicit_defaults)
        except ValueError as exc:
            parser.error(str(exc))
        if not names:
            print(f"No parameter profiles are available in {resolved_defaults}.")
            return 0
        print(f"Available parameter profiles in {resolved_defaults}:\n")
        for name in names:
            print(f"  {name}")
        return 0

    try:
        selection_requires_existing_defaults = explicit_defaults and not (
            args.generate_profile is not None and args.write_profile and args.parameter_profile is None
        )
        selected_parameters = select_parameter_profile(
            args.parameter_profile,
            resolved_defaults,
            explicit_defaults=selection_requires_existing_defaults,
        )
        cli_settings = explicit_parameter_settings(args)
    except ValueError as exc:
        parser.error(str(exc))

    if args.generate_profile is not None:
        try:
            generated_name = validate_parameter_profile_name(args.generate_profile)
            generated_settings = generated_profile_settings(selected_parameters, cli_settings)
            if args.write_profile:
                write_parameter_profile(
                    resolved_defaults,
                    generated_name,
                    generated_settings,
                    overwrite=args.overwrite_profile,
                )
                action = "Replaced" if args.overwrite_profile else "Added"
                print(
                    f"{action} parameter profile {generated_name!r} in {resolved_defaults}.",
                    file=sys.stderr,
                )
            else:
                print(format_profile_document(generated_name, generated_settings), end="")
        except ValueError as exc:
            parser.error(str(exc))
        return 0

    try:
        resolved_parameters = resolve_parameter_settings(selected_parameters, cli_settings)
        input_source = resolve_input(args)
        validate_remove_completed_ids(args, input_source)
        output_profile = resolve_profile(args.output_profile)
        explanatory_only = args.dry_run or args.explain or args.explain_json
        executable = validate_environment(dry_run=explanatory_only)
        plan = create_download_plan(
            executable=executable,
            resolved_parameters=resolved_parameters,
            input_source=input_source,
            output_profile=output_profile,
            defaults_file=resolved_defaults,
            parameter_profile=selected_parameters,
            remove_completed_ids=args.remove_completed_ids,
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    if args.explain_json:
        print(json.dumps(explain_plan_payload(plan), indent=2, ensure_ascii=False))
        return 0
    if args.explain:
        print(format_plan_explanation(plan))
        return 0

    manifest_targets: list[str] | None = None
    manifest_started_at: str | None = None
    manifest_yt_dlp_version: str | None = None
    output_event_file: Path | None = None
    if args.run_manifest is not None:
        try:
            manifest_targets = manifest_input_targets(input_source)
        except RuntimeError as exc:
            parser.error(str(exc))
        manifest_started_at = utc_timestamp()
        manifest_yt_dlp_version = yt_dlp_version(plan.executable)

    queue_requested: tuple[str, ...] = ()
    archive_before: set[str] = set()
    if args.remove_completed_ids and not args.dry_run:
        assert input_source.batch_file is not None
        try:
            queue_requested = queue_targets(input_source.batch_file)
            archive_before = archived_video_ids(plan.policy.archive_file)
            removed = remove_archived_ids(input_source.batch_file, plan.policy.archive_file)
        except RuntimeError as exc:
            parser.error(str(exc))
        if removed:
            print(
                f"Removed {removed} ID(s) already recorded in {plan.policy.archive_file} "
                f"from {input_source.batch_file}.",
                file=sys.stderr,
            )

    if args.run_manifest is not None:
        descriptor, event_name = tempfile.mkstemp(prefix="yt-download-output-", suffix=".jsonl")
        os.close(descriptor)
        output_event_file = Path(event_name)

    exit_status = run(plan.command(output_event_file=output_event_file), dry_run=args.dry_run)

    queue_report_payload: dict[str, object] | None = None
    if args.remove_completed_ids and not args.dry_run:
        assert input_source.batch_file is not None
        try:
            remaining = queue_targets(input_source.batch_file)
            report = queue_run_report(
                queue_file=input_source.batch_file,
                archive_file=plan.policy.archive_file,
                requested=queue_requested,
                archived_before=archive_before,
                remaining=remaining,
                exit_status=exit_status,
            )
            queue_report_payload = report
            counts = report["counts"]
            print(
                "Queue summary: "
                f"requested={counts['requested']}, "
                f"already-archived={counts['already_archived']}, "
                f"completed={counts['completed']}, "
                f"unresolved={counts['unresolved']}, "
                f"exit={exit_status}.",
                file=sys.stderr,
            )
            if args.queue_report is not None:
                write_queue_report(args.queue_report, report)
            if args.failed_targets is not None:
                write_failed_targets(args.failed_targets, report["targets"]["unresolved"])
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            if output_event_file is not None:
                try:
                    output_event_file.unlink(missing_ok=True)
                except OSError:
                    pass
            return 1 if exit_status == 0 else exit_status

    if args.run_manifest is not None:
        assert manifest_started_at is not None
        assert output_event_file is not None
        try:
            output_paths = read_output_records(output_event_file)
            outputs = output_manifest_entries(output_paths, hash_outputs=args.hash_outputs)
            manifest = run_manifest_payload(
                plan=plan,
                yt_dlp_version_value=manifest_yt_dlp_version,
                started_at=manifest_started_at,
                ended_at=utc_timestamp(),
                exit_status=exit_status,
                targets=manifest_targets,
                outputs=outputs,
                queue_report=queue_report_payload,
                hash_outputs=args.hash_outputs,
            )
            write_run_manifest(args.run_manifest, manifest)
        except RuntimeError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1 if exit_status == 0 else exit_status
        finally:
            try:
                output_event_file.unlink(missing_ok=True)
            except OSError:
                pass

    return exit_status


if __name__ == "__main__":
    raise SystemExit(main())
