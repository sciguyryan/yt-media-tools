#!/usr/bin/env python3

import argparse
import pathlib
import shlex
import shutil
import subprocess
import sys


VERSION = "0.2.1"

DEFAULT_PROFILE = "default"
DEFAULT_OUTPUT = "/mnt/storage/Downloads/YouTube"
DEFAULT_BATCH_FILE = "ids.txt"
DEFAULT_COOKIES = "cookies.txt"
DEFAULT_ARCHIVE = "archive.txt"
DEFAULT_RATE_LIMIT = "2M"
DEFAULT_RESOLUTION = 1440

SUPPORTED_RESOLUTIONS = (360, 480, 720, 1080, 1440, 2160)


def script_directory() -> pathlib.Path:
    return pathlib.Path(__file__).resolve().parent


def default_local_path(name: str) -> str:
    return str(script_directory() / name)


def profile_directory() -> pathlib.Path:
    return script_directory() / "profiles"


def resolution(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("resolution must be a number") from exc

    if parsed not in SUPPORTED_RESOLUTIONS:
        choices = ", ".join(str(item) for item in SUPPORTED_RESOLUTIONS)
        raise argparse.ArgumentTypeError(
            f"unsupported resolution {parsed}; choose one of: {choices}"
        )

    return parsed


def load_profile(name: str) -> dict[str, str]:
    path = pathlib.Path(name)
    if not path.is_file():
        path = profile_directory() / name

    if not path.is_file():
        raise ValueError(f"profile not found: {name}")

    path = path.resolve()
    settings: dict[str, str] = {}
    path_keys = {"batch_file", "cookies", "archive"}

    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected key=value")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if key in path_keys:
            value_path = pathlib.Path(value)
            if not value_path.is_absolute():
                value = str((path.parent / value_path).resolve())

        settings[key] = value

    return settings


def parse_args() -> argparse.Namespace:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "-p",
        "--profile",
        default=DEFAULT_PROFILE,
        help="Downloader profile to load",
    )
    pre_args, _ = pre_parser.parse_known_args()

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
    parser.add_argument("targets", nargs="*", help="Video URLs or IDs to download")
    parser.add_argument(
        "-b",
        "--batch-file",
        default=profile.get("batch_file", default_local_path(DEFAULT_BATCH_FILE)),
        help=f"Read targets from a batch file (default: {DEFAULT_BATCH_FILE})",
    )
    parser.add_argument(
        "-r",
        "--resolution",
        type=resolution,
        default=profile.get("resolution", str(DEFAULT_RESOLUTION)),
        help=f"Preferred maximum video height (default: {DEFAULT_RESOLUTION})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=profile.get("output", DEFAULT_OUTPUT),
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--cookies",
        default=profile.get("cookies", default_local_path(DEFAULT_COOKIES)),
        help=f"Cookies file (default: {DEFAULT_COOKIES})",
    )
    parser.add_argument(
        "--archive",
        default=profile.get("archive", default_local_path(DEFAULT_ARCHIVE)),
        help=f"Download archive (default: {DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--rate-limit",
        default=profile.get("rate_limit", DEFAULT_RATE_LIMIT),
        help=f"Download rate limit (default: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--playlist-reverse",
        action="store_true",
        default=profile.get("playlist_reverse", "").lower() in {"1", "true", "yes"},
        help="Download playlist entries in reverse order",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the yt-dlp command without running it",
    )

    args = parser.parse_args()

    if isinstance(args.resolution, str):
        try:
            args.resolution = resolution(args.resolution)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))

    return args


def validate_args(args: argparse.Namespace) -> str | None:
    if args.targets:
        return None

    batch_file = pathlib.Path(args.batch_file)
    if not batch_file.is_file():
        return f"batch file not found: {batch_file}"

    return None


def build_command(args: argparse.Namespace) -> list[str]:
    command = [
        "yt-dlp",
        "--cookies",
        args.cookies,
        "--download-archive",
        args.archive,
        "--limit-rate",
        args.rate_limit,
        "--windows-filenames",
        "--embed-metadata",
        "--embed-thumbnail",
        "--write-subs",
        "--sub-langs",
        "en.*",
        "-f",
        f"bv*[height<={args.resolution}]+ba/b[height<={args.resolution}]",
        "-o",
        f"{args.output}/%(title)s [%(id)s].%(ext)s",
    ]

    if args.playlist_reverse:
        command.append("--playlist-reverse")

    if args.targets:
        command.extend(args.targets)
    else:
        command.extend(["--batch-file", args.batch_file])

    return command


def main() -> int:
    args = parse_args()

    error = validate_args(args)
    if error:
        print(error, file=sys.stderr)
        return 2

    command = build_command(args)

    if args.dry_run:
        print(shlex.join(command))
        return 0

    if shutil.which("yt-dlp") is None:
        print("yt-dlp was not found in PATH.", file=sys.stderr)
        return 1

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
