from __future__ import annotations

import time
from pathlib import Path

import pytest

from yt_media_tools.cookies import CookieFileError, cookie_header_from_netscape_file


def _write(path: Path, lines: list[str]) -> Path:
    path.write_text("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_netscape_cookie_file_becomes_youtube_cookie_header(tmp_path: Path) -> None:
    future = int(time.time()) + 3600
    path = _write(
        tmp_path / "cookies.txt",
        [
            f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSID\tsecret-one",
            f".youtube.com\tTRUE\t/\tTRUE\t{future}\tHSID\tsecret-two",
            f".example.com\tTRUE\t/\tTRUE\t{future}\tOTHER\tnot-for-youtube",
        ],
    )
    header, values = cookie_header_from_netscape_file(path)
    assert "SID=secret-one" in header
    assert "HSID=secret-two" in header
    assert "OTHER=" not in header
    assert set(values) == {"secret-one", "secret-two"}


def test_expired_cookie_is_not_forwarded(tmp_path: Path) -> None:
    past = int(time.time()) - 3600
    future = int(time.time()) + 3600
    path = _write(
        tmp_path / "cookies.txt",
        [
            f".youtube.com\tTRUE\t/\tTRUE\t{past}\tOLD\texpired-secret",
            f".youtube.com\tTRUE\t/\tTRUE\t{future}\tSID\tcurrent-secret",
        ],
    )
    header, values = cookie_header_from_netscape_file(path)
    assert "OLD=" not in header
    assert "SID=current-secret" in header
    assert values == ("current-secret",)


def test_cookie_file_without_applicable_youtube_cookies_is_rejected(tmp_path: Path) -> None:
    future = int(time.time()) + 3600
    path = _write(tmp_path / "cookies.txt", [f".example.com\tTRUE\t/\tTRUE\t{future}\tSID\tsecret"])
    with pytest.raises(CookieFileError, match="no applicable unexpired cookies"):
        cookie_header_from_netscape_file(path)
