#!/usr/bin/env python3

import argparse
import pathlib
import shlex
import shutil
import subprocess
import sys

VERSION = "1.1.0"
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
    return sorted(
        path.name
        for path in directory.iterdir()
        if path.is_file() and not path.name.startswith(".")
    )


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
                raise ValueError(
                    f"{path}:{line_number}: expected {PROFILE_SIGNATURE} profile signature"
                )
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
        help="Remove IDs already present in the download archive from the batch file",
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
    return [
        line.strip()
        for line in sys.stdin
        if line.strip() and not line.lstrip().startswith("#")
    ]


def resolve_targets(args: argparse.Namespace) -> tuple[list[str], str | None]:
    targets: list[str] = []

    if args.input_file:
        if args.targets:
            return [], "--input-file cannot be combined with positional targets"
        input_path = pathlib.Path(args.input_file)
        if not input_path.is_file():
            return [], f"input file not found: {input_path}"
        args.batch_file = str(input_path)
        return [], None

    for target in args.targets:
        if target == "-":
            if len(args.targets) != 1:
                return (
                    [],
                    "'-' for standard input cannot be combined with other targets",
                )
            targets.extend(read_stdin_targets())
        else:
            targets.append(target)

    if len(targets) == 1:
        possible_file = pathlib.Path(targets[0])
        if possible_file.is_file():
            args.batch_file = str(possible_file)
            return [], None

    if targets:
        return targets, None

    if args.targets:
        return [], "no download targets were supplied on standard input"

    batch_file = pathlib.Path(args.batch_file)
    if not batch_file.is_file():
        return [], f"batch file not found: {batch_file}"

    return [], None


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
        "--embed-metadata",
        "--embed-thumbnail",
        "--write-subs",
        "--sub-langs",
        "en.*",
        "-f",
        f"bv*[height<={args.resolution}]+ba/b[height<={args.resolution}]",
        "-o",
        output_path,
    ]

    if args.playlist_reverse:
        command.append("--playlist-reverse")

    if targets:
        command.extend(targets)
    else:
        command.extend(["--batch-file", args.batch_file])

    return command


def main() -> int:
    args = parse_args()

    targets, error = resolve_targets(args)
    if error:
        print(error, file=sys.stderr)
        return 2

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
            print(
                f"Removed {removed} archived ID(s) from {args.batch_file} before download."
            )

    completed = subprocess.run(command, check=False)

    if completed.returncode == 0 and args.remove_completed_ids:
        removed = remove_completed_ids(
            pathlib.Path(args.batch_file),
            pathlib.Path(args.archive),
        )
        if removed:
            print(f"Removed {removed} completed ID(s) from {args.batch_file}.")

    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
