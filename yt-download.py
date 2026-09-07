#!/usr/bin/env python3

import argparse
from dataclasses import dataclass
import pathlib
import shlex
import shutil
import subprocess
import sys


VERSION = "1.4.0"
SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
PROFILES_DIR = SCRIPT_DIR / "profiles"

DEFAULT_PROFILE = "default"
PROFILE_KEYS = {"path", "output"}
PROFILE_SIGNATURE = "@profile"
DEFAULT_OUTPUT = "/mnt/storage/Downloads/YouTube"
DEFAULT_BATCH_FILE = "ids.txt"
DEFAULT_COOKIES = "cookies.txt"
DEFAULT_ARCHIVE = "archive.txt"
DEFAULT_RATE_LIMIT = "20M"
DEFAULT_RESOLUTION = 1440


@dataclass(frozen=True)
class InputSource:
    """Resolved downloader input source."""

    kind: str
    targets: list[str]
    batch_file: pathlib.Path | None = None


def script_directory() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def default_local_path(name: str) -> str:
    return str(script_directory() / name)


def profile_directory() -> pathlib.Path:
    return PROFILES_DIR


def resolution(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("resolution must be a number") from exc

    if parsed <= 0:
        raise argparse.ArgumentTypeError("resolution must be a positive number")

    return parsed


def rate_limit(value: str) -> str:
    value = value.strip()
    if not value:
        raise argparse.ArgumentTypeError("rate limit cannot be empty")

    number = value[:-1] if value[-1:].upper() in {"K", "M", "G"} else value
    try:
        if float(number) <= 0:
            raise ValueError
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "rate limit must be a positive number, optionally followed by K, M or G"
        ) from exc

    return value


def available_profiles() -> list[str]:
    directory = profile_directory()
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.iterdir() if path.is_file() and not path.name.startswith("."))


def load_profile(name: str) -> dict[str, str]:
    requested = pathlib.Path(name)
    explicit_path = requested.is_absolute() or requested.parent != pathlib.Path(".")
    path = requested if explicit_path else profile_directory() / name

    if not path.is_file() and not explicit_path and name != DEFAULT_PROFILE:
        fallback = profile_directory() / DEFAULT_PROFILE
        if fallback.is_file():
            print(
                f"warning: profile not found: {name}; using {DEFAULT_PROFILE}",
                file=sys.stderr,
            )
            path = fallback

    if not path.is_file():
        if not explicit_path:
            print(
                "warning: no usable output profile found; using yt-dlp output defaults",
                file=sys.stderr,
            )
            return {}
        raise ValueError(f"profile not found: {name}")

    lines = path.resolve().read_text(encoding="utf-8").splitlines()
    signature_seen = False
    settings: dict[str, str] = {}

    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if not signature_seen:
            if line != PROFILE_SIGNATURE:
                raise ValueError(f"{path}:{line_number}: expected {PROFILE_SIGNATURE} profile signature")
            signature_seen = True
            continue

        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected key=value")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key:
            raise ValueError(f"{path}:{line_number}: empty profile key")
        if key in settings:
            raise ValueError(f"{path}:{line_number}: duplicate profile key: {key}")
        if key not in PROFILE_KEYS:
            raise ValueError(f"{path}:{line_number}: unsupported profile key: {key}")
        if not value:
            raise ValueError(f"{path}:{line_number}: empty value for {key}")

        settings[key] = value

    if not signature_seen:
        raise ValueError(f"{path}: missing {PROFILE_SIGNATURE} profile signature")
    if not settings:
        raise ValueError(f"{path}: profile must define path, output, or both")

    return settings


def parse_args() -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "-p",
        "--profile",
        default=DEFAULT_PROFILE,
        help="Downloader profile to load",
    )
    pre_parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List available downloader profiles and exit",
    )
    pre_args, _ = pre_parser.parse_known_args()

    if pre_args.list_profiles:
        for name in available_profiles():
            print(name)
        raise SystemExit(0)

    try:
        profile = load_profile(pre_args.profile)
    except ValueError as exc:
        pre_parser.error(str(exc))

    parser = argparse.ArgumentParser(
        description="Download YouTube videos with my usual yt-dlp settings.",
        parents=[pre_parser],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )
    parser.add_argument(
        "--examples",
        action="store_true",
        help="Show practical usage examples and exit",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        help="Video URLs or IDs to download; use - to read targets from standard input",
    )
    parser.add_argument(
        "-b",
        "--batch-file",
        default=default_local_path(DEFAULT_BATCH_FILE),
        help=f"Read targets from a batch file (default: {DEFAULT_BATCH_FILE})",
    )
    parser.add_argument(
        "--input-file",
        help="Read targets from this file instead of positional targets or the default batch file",
    )
    parser.add_argument(
        "-r",
        "--resolution",
        type=resolution,
        default=str(DEFAULT_RESOLUTION),
        help=f"Preferred maximum video height (default: {DEFAULT_RESOLUTION})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=profile.get("path", DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--cookies",
        default=default_local_path(DEFAULT_COOKIES),
        help=f"Cookies file (default: {DEFAULT_COOKIES})",
    )
    parser.add_argument(
        "--archive",
        default=default_local_path(DEFAULT_ARCHIVE),
        help=f"Download archive (default: {DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--rate-limit",
        type=rate_limit,
        default=DEFAULT_RATE_LIMIT,
        help=f"Download rate limit (default: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--playlist-reverse",
        "--rev",
        action="store_true",
        default=False,
        help="Download playlist entries in reverse order",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the yt-dlp command without running it",
    )
    parser.add_argument(
        "--remove-completed-ids",
        action="store_true",
        help="Remove completed IDs from a file-backed queue as downloads finish",
    )
    parser.add_argument(
        "--_remove-completed-id",
        metavar="VIDEO_ID",
        help=argparse.SUPPRESS,
    )

    args = parser.parse_args()
    args.profile_output = profile.get("output")

    if args.examples:
        print("""Examples:
  yt-download.py VIDEO_URL
  yt-download.py PLAYLIST_URL --rev
  yt-download.py --input-file ./ids/ids
  yt-download.py ./ids/ids --resolution 1440
  yt-download.py --profile playlist PLAYLIST_URL
  yt-download.py --dry-run VIDEO_URL
""")
        raise SystemExit(0)

    if isinstance(args.resolution, str):
        try:
            args.resolution = resolution(args.resolution)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))

    if isinstance(args.rate_limit, str):
        try:
            args.rate_limit = rate_limit(args.rate_limit)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))

    return args


def read_stdin_targets() -> list[str]:
    return [line.strip() for line in sys.stdin if line.strip() and not line.lstrip().startswith("#")]


def resolve_input_source(
    args: argparse.Namespace,
) -> tuple[InputSource | None, str | None]:
    """Resolve CLI input into one explicit source without changing its content."""

    if args.input_file:
        if args.targets:
            return None, "--input-file cannot be combined with positional targets"
        input_path = pathlib.Path(args.input_file)
        if not input_path.is_file():
            return None, f"input file not found: {input_path}"
        return InputSource("file", [], input_path), None

    if "-" in args.targets:
        if len(args.targets) != 1:
            return None, "'-' for standard input cannot be combined with other targets"
        targets = read_stdin_targets()
        if not targets:
            return None, "no download targets were supplied on standard input"
        return InputSource("stdin", targets), None

    targets = list(args.targets)
    if len(targets) == 1:
        possible_file = pathlib.Path(targets[0])
        if possible_file.is_file():
            return InputSource("file", [], possible_file), None

    if targets:
        return InputSource("direct", targets), None

    batch_file = pathlib.Path(args.batch_file)
    if not batch_file.is_file():
        return None, f"batch file not found: {batch_file}"

    return InputSource("file", [], batch_file), None


def resolve_targets(args: argparse.Namespace) -> tuple[list[str], str | None]:
    """Compatibility wrapper around the resolved input-source model."""

    source, error = resolve_input_source(args)
    if error or source is None:
        return [], error

    if source.batch_file is not None:
        args.batch_file = str(source.batch_file)

    return source.targets, None


def validate_remove_completed_ids(
    args: argparse.Namespace,
    targets: list[str],
) -> str | None:
    if not args.remove_completed_ids:
        return None
    if targets:
        return "--remove-completed-ids requires a batch or input file"
    return None


def validate_runtime_files(args: argparse.Namespace) -> str | None:
    cookies = pathlib.Path(args.cookies)
    if not cookies.is_file():
        return f"cookies file not found: {cookies}"

    archive = pathlib.Path(args.archive)
    if archive.exists() and not archive.is_file():
        return f"archive path is not a file: {archive}"

    output = pathlib.Path(args.output)
    if output.exists() and not output.is_dir():
        return f"output path is not a directory: {output}"

    return None


def completed_ids(archive_path: pathlib.Path) -> set[str]:
    if not archive_path.is_file():
        return set()

    completed: set[str] = set()
    for raw_line in archive_path.read_text(encoding="utf-8-sig").splitlines():
        parts = raw_line.strip().split()
        if len(parts) >= 2:
            completed.add(parts[-1])

    return completed


def remove_completed_ids(batch_path: pathlib.Path, archive_path: pathlib.Path) -> int:
    completed = completed_ids(archive_path)
    if not completed:
        return 0

    original = batch_path.read_bytes()
    retained: list[bytes] = []
    removed = 0

    for raw_line in original.splitlines(keepends=True):
        candidate = raw_line.strip()
        if candidate and candidate.decode("utf-8") in completed:
            removed += 1
            continue
        retained.append(raw_line)

    if not removed:
        return 0

    temporary_path = batch_path.with_name(batch_path.name + ".tmp")
    temporary_path.write_bytes(b"".join(retained))
    temporary_path.replace(batch_path)
    return removed


def remove_completed_id(batch_path: pathlib.Path, video_id: str) -> bool:
    """Remove the first exact video ID line without changing unrelated queue bytes."""

    original = batch_path.read_bytes()
    retained: list[bytes] = []
    removed = False

    for raw_line in original.splitlines(keepends=True):
        candidate = raw_line.strip()
        if not removed and candidate and candidate.decode("utf-8") == video_id:
            removed = True
            continue
        retained.append(raw_line)

    if not removed:
        return False

    temporary_path = batch_path.with_name(batch_path.name + ".tmp")
    temporary_path.write_bytes(b"".join(retained))
    temporary_path.replace(batch_path)
    return True


def build_command(args: argparse.Namespace, targets: list[str]) -> list[str]:
    output_template = args.profile_output or "%(title)s [%(id)s].%(ext)s"
    output_path = f"{args.output.rstrip('/')}/{output_template.lstrip('/')}"

    command = [
        "yt-dlp",
        "--cookies",
        args.cookies,
        "--download-archive",
        args.archive,
        "--limit-rate",
        args.rate_limit,
        "--windows-filenames",
        "--mtime",
        "--embed-chapters",
        "--embed-metadata",
        "--embed-thumbnail",
        "--embed-subs",
        "--sub-langs",
        "all,-live_chat",
        "--sponsorblock-remove",
        "all",
        "--video-multistreams",
        "--audio-multistreams",
        "--paths",
        "temp:/mnt/storage/Temp/yt-dlp",
        "--format-sort",
        f"res:{args.resolution}",
        "--extractor-args",
        "youtube:player-client=default,-android_sdkless",
        "-f",
        "bv+ba/best",
        "-o",
        output_path,
    ]

    if args.playlist_reverse:
        command.append("--playlist-reverse")

    if getattr(args, "remove_completed_ids", False) and not targets:
        command.extend(
            [
                "--exec",
                "after_move:"
                + shlex.join(
                    [
                        sys.executable,
                        str(pathlib.Path(__file__).resolve()),
                        "--_remove-completed-id",
                        "%(id)s",
                        "--batch-file",
                        args.batch_file,
                    ]
                ),
            ]
        )

    if targets:
        command.extend(targets)
    else:
        command.extend(["--batch-file", args.batch_file])

    return command


def main() -> int:
    args = parse_args()

    if args._remove_completed_id:
        batch_path = pathlib.Path(args.batch_file)
        if not batch_path.is_file():
            print(f"batch file not found: {batch_path}", file=sys.stderr)
            return 2
        remove_completed_id(batch_path, args._remove_completed_id)
        return 0

    source, error = resolve_input_source(args)
    if error or source is None:
        print(error, file=sys.stderr)
        return 2

    targets = source.targets
    if source.batch_file is not None:
        args.batch_file = str(source.batch_file)

    error = validate_remove_completed_ids(args, targets)
    if error:
        print(error, file=sys.stderr)
        return 2

    command = build_command(args, targets)

    if args.dry_run:
        print(shlex.join(command))
        return 0

    error = validate_runtime_files(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    if shutil.which("yt-dlp") is None:
        print("yt-dlp was not found in PATH.", file=sys.stderr)
        return 1

    if args.remove_completed_ids:
        removed = remove_completed_ids(
            pathlib.Path(args.batch_file),
            pathlib.Path(args.archive),
        )
        if removed:
            print(f"Removed {removed} archived ID(s) from {args.batch_file} before download.")

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
