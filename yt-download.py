#!/usr/bin/env python3

import argparse
import subprocess
import sys

DEFAULT_OUTPUT = "/mnt/storage/Downloads/YouTube"
DEFAULT_BATCH_FILE = "ids.txt"
DEFAULT_COOKIES = "cookies.txt"
DEFAULT_ARCHIVE = "archive.txt"
DEFAULT_RATE_LIMIT = "2M"
DEFAULT_RESOLUTION = "1440"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download YouTube videos with my usual yt-dlp settings."
    )
    parser.add_argument("targets", nargs="*", help="Video URLs or IDs to download")
    parser.add_argument(
        "-b",
        "--batch-file",
        default=DEFAULT_BATCH_FILE,
        help=f"Read targets from a batch file (default: {DEFAULT_BATCH_FILE})",
    )
    parser.add_argument(
        "-r",
        "--resolution",
        default=DEFAULT_RESOLUTION,
        help=f"Preferred maximum video height (default: {DEFAULT_RESOLUTION})",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--cookies",
        default=DEFAULT_COOKIES,
        help=f"Cookies file (default: {DEFAULT_COOKIES})",
    )
    parser.add_argument(
        "--archive",
        default=DEFAULT_ARCHIVE,
        help=f"Download archive (default: {DEFAULT_ARCHIVE})",
    )
    parser.add_argument(
        "--rate-limit",
        default=DEFAULT_RATE_LIMIT,
        help=f"Download rate limit (default: {DEFAULT_RATE_LIMIT})",
    )
    parser.add_argument(
        "--playlist-reverse",
        action="store_true",
        help="Download playlist entries in reverse order",
    )
    return parser.parse_args()


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
    command = build_command(args)

    try:
        completed = subprocess.run(command, check=False)
    except FileNotFoundError:
        print("yt-dlp was not found.", file=sys.stderr)
        return 1

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
