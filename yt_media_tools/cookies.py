"""Cookie-file translation helpers for provider adapters."""

from __future__ import annotations

import http.cookiejar
import urllib.request
from pathlib import Path


class CookieFileError(ValueError):
    """Raised when a Netscape cookie file cannot be consumed safely."""


def cookie_header_from_netscape_file(
    path: Path, *, url: str = "https://www.youtube.com/"
) -> tuple[str, tuple[str, ...]]:
    """Return an applicable HTTP Cookie header and its values from a Netscape cookie file.

    MozillaCookieJar applies domain, path, secure and expiry policy when adding cookies to the
    request. The returned values are retained only so callers can keep credentials out of
    diagnostics and serialised reports.
    """
    jar = http.cookiejar.MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=False)
    except (OSError, http.cookiejar.LoadError) as exc:
        raise CookieFileError(f"could not read Netscape cookies file: {path}") from exc

    request = urllib.request.Request(url)
    jar.add_cookie_header(request)
    header = request.get_header("Cookie")
    if not header:
        raise CookieFileError(f"Netscape cookies file contains no applicable unexpired cookies for {url}")

    applicable_values: list[str] = []
    for cookie in jar:
        probe = urllib.request.Request(url)
        single = http.cookiejar.CookieJar()
        single.set_cookie(cookie)
        single.add_cookie_header(probe)
        if probe.get_header("Cookie") is not None:
            applicable_values.append(cookie.value)
    return header, tuple(applicable_values)
