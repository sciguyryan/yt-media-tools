"""Shared low-level runtime helpers for invoking yt-dlp.

This module owns mechanics that should behave consistently across Discover and
Downloader. Higher-level acquisition and download policy remain component-owned.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Sequence


class YtDlpRuntimeError(RuntimeError):
    """Raised when the yt-dlp runtime cannot satisfy an invocation request."""


def resolve_executable(*, dry_run: bool = False, command_name: str = "yt-dlp") -> str:
    """Resolve the yt-dlp executable while allowing unresolved dry-run planning."""
    executable = shutil.which(command_name)
    if executable is not None:
        return executable
    if dry_run:
        return command_name
    raise YtDlpRuntimeError(f"{command_name} was not found on PATH")


def ensure_executable(command_name: str = "yt-dlp") -> None:
    """Require yt-dlp to be available on PATH."""
    resolve_executable(command_name=command_name)


def probe_version(executable: str) -> str | None:
    """Return the invoked yt-dlp version without making execution depend on it."""
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


def resolve_cookie_file(
    requested: Path | None,
    *,
    default_file: Path,
    disabled: bool = False,
) -> Path | None:
    """Resolve an explicit or optional default cookie file.

    Explicitly requested files are validated strictly. The default file is
    opportunistic and is used only when it exists.
    """
    if disabled:
        return None
    if requested is not None:
        path = requested.expanduser()
        if not path.is_file():
            raise ValueError(f"cookies file not found: {path}")
        return path
    if default_file.is_file():
        return default_file
    return None


def append_authentication_options(
    command: list[str],
    *,
    cookies_file: Path | None = None,
    cookies_from_browser: str | None = None,
) -> None:
    """Append one mutually exclusive yt-dlp cookie source to a command."""
    if cookies_file is not None:
        command.extend(("--cookies", str(cookies_file)))
    elif cookies_from_browser is not None:
        command.extend(("--cookies-from-browser", cookies_from_browser))


def format_command(command: Sequence[str]) -> str:
    """Return a shell-readable representation of a command for diagnostics."""
    return shlex.join(command)
