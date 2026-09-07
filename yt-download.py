#!/usr/bin/env python3
"""Download media through yt-dlp using a small, predictable wrapper.

The downloader keeps global download policy in Python while delegating output
location and naming to optional output profiles stored beside the script in the
``profiles`` directory.

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
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


PROGRAM_NAME = "yt-download.py"
PROGRAM_VERSION = "1.7.0"

SCRIPT_DIR = Path(__file__).resolve().parent
PROFILES_DIR = SCRIPT_DIR / "profiles"
DEFAULT_PROFILE_NAME = "default"
PROFILE_SIGNATURE = "@profile"
DEFAULTS_FILE = SCRIPT_DIR / "defaults.json"
PARAMETER_PROFILE_VERSION = 1
PARAMETER_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PARAMETER_PROFILE_KEYS = (
    "resolution",
    "format",
    "cookies",
    "no-cookies",
    "reverse-playlist",
    "playlist",
)

DEFAULT_VIDEO_ID_FILE = Path("./ids.txt")
ARCHIVE_FILE = SCRIPT_DIR / "archive.txt"
COOKIES_FILE = SCRIPT_DIR / "cookies.txt"
TEMP_DIR = Path("/mnt/storage/Temp/yt-dlp")

DEFAULT_RESOLUTION = "1440"
DOWNLOAD_RATE = "20M"
FORMAT_SELECTOR = "bv+ba/best"
EXTRACTOR_ARGS = "youtube:player-client=default,-android_sdkless"

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

  Reverse playlist traversal:
    %(prog)s --rev PLAYLIST_URL

  Combine parameter-profile selection, an explicit override and playlist reversal:
    %(prog)s -p playlist -r 1440 --rev PLAYLIST_URL

  Remove IDs from a batch file immediately after each video is fully processed:
    %(prog)s --remove-completed-ids ids/batch.txt
    %(prog)s --remove-completed-ids --input-file ids/batch.txt

  A failed, skipped, interrupted or partially processed video remains in the file.
  The removal callback runs at yt-dlp's after_move stage, after successful post-processing.

  Use an explicit cookies file when authentication is required:
    %(prog)s --cookies /path/to/cookies.txt VIDEO_ID

  Ignore an automatically discovered script-local cookies.txt:
    %(prog)s --no-cookies VIDEO_ID

  Print the resolved yt-dlp command without executing it:
    %(prog)s --dry-run -p playlist PLAYLIST_URL

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

    @property
    def sort_selector(self) -> str:
        """Return yt-dlp's format sort expression for the requested resolution."""
        if self.resolution == "best":
            return "res,lang,fps,size"
        return f"res:{self.resolution},lang,fps,size"


@dataclass(frozen=True)
class ParameterProfile:
    """One validated named Downloader parameter profile."""

    name: str
    settings: dict[str, object]
    source: Path


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
        "--_remove-completed-id",
        nargs=2,
        metavar=("FILE", "VIDEO_ID"),
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
    if key == "cookies":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("parameter setting 'cookies' must be a non-empty JSON string")
        return value
    if key in {"no-cookies", "reverse-playlist", "playlist"}:
        if not isinstance(value, bool):
            raise ValueError(f"parameter setting {key!r} must be a JSON Boolean")
        return value
    raise ValueError(f"unknown parameter setting {key!r}")


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

    if "cookies" in validated and "no-cookies" in validated:
        raise ValueError(f"parameter profile {profile_name!r} cannot define both 'cookies' and 'no-cookies'")
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
    if args.resolution is not None:
        validate_resolution(args.resolution)
        settings["resolution"] = args.resolution
    if args.format_selector is not None:
        settings["format"] = _validate_parameter_setting("format", args.format_selector)
    if args.reverse_playlist is not None:
        settings["reverse-playlist"] = args.reverse_playlist
    if args.playlist is not None:
        settings["playlist"] = args.playlist
    if args.cookies is not None:
        settings["cookies"] = str(args.cookies.expanduser())
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
    if "cookies" in cli_settings:
        merged.pop("no-cookies", None)
    if "no-cookies" in cli_settings:
        merged.pop("cookies", None)
    merged.update(cli_settings)
    return merged


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
) -> tuple[DownloadPolicy, Path | None, bool]:
    """Resolve merged profile settings into Downloader runtime policy."""
    resolution = validate_resolution(str(settings.get("resolution", DEFAULT_RESOLUTION)))
    format_selector = str(settings.get("format", FORMAT_SELECTOR))
    reverse_playlist = bool(settings.get("reverse-playlist", False))
    playlist_value = settings.get("playlist")
    playlist = playlist_value if isinstance(playlist_value, bool) else None

    if "cookies" in settings:
        cookie_path = Path(str(settings["cookies"])).expanduser()
        cookies_file = resolve_cookies(cookie_path, disabled=False)
    else:
        disabled = bool(settings.get("no-cookies", False))
        cookies_file = resolve_cookies(None, disabled=disabled)

    return (
        DownloadPolicy(
            resolution=resolution,
            format_selector=format_selector,
            reverse_playlist=reverse_playlist,
            playlist=playlist,
        ),
        cookies_file,
        bool(settings.get("no-cookies", False)),
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


def validate_remove_completed_ids(args: argparse.Namespace, input_source: InputSource) -> None:
    """Validate the public completed-ID removal mode."""
    if not args.remove_completed_ids:
        return
    if input_source.batch_file is None:
        raise ValueError(
            "--remove-completed-ids requires file input; use --input-file FILE, "
            "a positional batch file, or the default ./ids.txt"
        )


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


def build_yt_dlp_command(
    executable: str,
    policy: DownloadPolicy,
    input_source: InputSource,
    profile: OutputProfile | None,
    *,
    cookies_file: Path | None = None,
    remove_completed_ids: bool = False,
) -> list[str]:
    """Build the complete yt-dlp command without invoking a shell."""
    command = [
        executable,
        "-f",
        policy.format_selector,
        "-S",
        policy.sort_selector,
        "-r",
        DOWNLOAD_RATE,
        "--mtime",
        "--embed-chapters",
        "--embed-metadata",
        "--sponsorblock-remove",
        "all",
        "--download-archive",
        str(ARCHIVE_FILE),
        "--video-multistreams",
        "--audio-multistreams",
    ]

    if cookies_file is not None:
        command.extend(("--cookies", str(cookies_file)))

    if profile is not None:
        if profile.output is not None:
            command.extend(("--output", profile.output))
        if profile.path is not None:
            command.extend(("--paths", f"home:{profile.path}"))

    command.extend(("--paths", f"temp:{TEMP_DIR}"))
    command.extend(("--extractor-args", EXTRACTOR_ARGS))

    if policy.reverse_playlist:
        command.append("--playlist-reverse")

    if policy.playlist is True:
        command.append("--yes-playlist")
    elif policy.playlist is False:
        command.append("--no-playlist")

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

    if args.examples:
        show_examples(parser)
        return 0

    resolved_defaults = defaults_path(args.defaults)
    explicit_defaults = args.defaults is not None

    if args.list_parameters and args.generate_profile is not None:
        parser.error("--list-parameters cannot be combined with --generate-profile")
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
        merged_settings = merge_parameter_settings(selected_parameters, cli_settings)
        policy, cookies_file, _cookies_disabled = resolve_parameter_policy(merged_settings)
        input_source = resolve_input(args)
        validate_remove_completed_ids(args, input_source)
        output_profile = resolve_profile(args.output_profile)
        executable = validate_environment(dry_run=args.dry_run)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    if args.remove_completed_ids and not args.dry_run:
        assert input_source.batch_file is not None
        try:
            removed = remove_archived_ids(input_source.batch_file, ARCHIVE_FILE)
        except RuntimeError as exc:
            parser.error(str(exc))
        if removed:
            print(
                f"Removed {removed} ID(s) already recorded in {ARCHIVE_FILE} from {input_source.batch_file}.",
                file=sys.stderr,
            )

    command = build_yt_dlp_command(
        executable,
        policy,
        input_source,
        output_profile,
        cookies_file=cookies_file,
        remove_completed_ids=args.remove_completed_ids,
    )
    return run(command, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
