from __future__ import annotations

from types import SimpleNamespace

import pytest

from yt_media_tools.discover_cli import build_parser
from yt_media_tools.network_proxy import ProxyConfiguration, parse_proxy_url, requests_proxy_mapping
from yt_media_tools.ytdlp import (
    build_lazy_flat_command,
    build_metadata_command,
    build_video_metadata_command,
    shell_join,
)


def test_socks5h_proxy_retains_remote_dns_policy_and_canonical_endpoint() -> None:
    proxy = parse_proxy_url("socks5h://127.0.0.1:45678")

    assert proxy == ProxyConfiguration("socks5h", "127.0.0.1", 45678)
    assert proxy.socks_version == 5
    assert proxy.remote_dns is True
    assert proxy.url == "socks5h://127.0.0.1:45678"
    assert requests_proxy_mapping(proxy) == {
        "http": "socks5h://127.0.0.1:45678",
        "https": "socks5h://127.0.0.1:45678",
    }


def test_proxy_credentials_round_trip_canonically_and_are_redacted() -> None:
    proxy = parse_proxy_url("socks5h://user%40name:p%20ass@[::1]:1080/")

    assert proxy.username == "user@name"
    assert proxy.password == "p ass"
    assert proxy.url == "socks5h://user%40name:p%20ass@[::1]:1080"
    assert proxy.redacted_url == "socks5h://<redacted>@[::1]:1080"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "must not be empty"),
        ("ftp://127.0.0.1:21", "unsupported proxy scheme"),
        ("socks5h://127.0.0.1", "explicit port"),
        ("socks5h://127.0.0.1:70000", "Port out of range"),
        ("socks5h://127.0.0.1:1080/path", "must not contain a path"),
    ],
)
def test_invalid_proxy_urls_are_rejected(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_proxy_url(value)


def test_cli_parses_proxy_into_typed_configuration() -> None:
    args = build_parser().parse_args(["--proxy", "socks5h://127.0.0.1:45678", "abc123XYZ00"])

    assert args.proxy == ProxyConfiguration("socks5h", "127.0.0.1", 45678)


def test_every_ytdlp_acquisition_command_receives_the_proxy() -> None:
    proxy = parse_proxy_url("socks5h://127.0.0.1:45678")
    commands = (
        build_metadata_command("https://example.invalid/source", cookies_file=None, proxy=proxy),
        build_lazy_flat_command("https://example.invalid/source", cookies_file=None, proxy=proxy),
        build_video_metadata_command(["abc123XYZ00"], cookies_file=None, proxy=proxy),
    )

    for command in commands:
        assert command[command.index("--proxy") + 1] == proxy.url


def test_normal_command_rendering_never_discloses_proxy_credentials() -> None:
    proxy = parse_proxy_url("socks5h://user:secret@127.0.0.1:45678")
    command = build_metadata_command("https://example.invalid/source", cookies_file=None, proxy=proxy)

    rendered = shell_join(command)

    assert "secret" not in rendered
    assert "user" not in rendered
    assert "--proxy '<redacted>'" in rendered


def test_ytmusicapi_receives_requests_proxy_mapping(monkeypatch) -> None:
    import yt_media_tools.ytmusic as backend

    captured = {}

    class FakeYTMusic:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def get_song(self, _video_id, **_kwargs):
            return {"videoDetails": {"title": "Song", "channelId": "artist"}}

    monkeypatch.setattr(backend.importlib, "import_module", lambda _name: SimpleNamespace(YTMusic=FakeYTMusic))
    proxy = parse_proxy_url("socks5h://127.0.0.1:45678")

    backend.acquire_song_metadata(["abc"], proxy=proxy)

    assert captured == {"proxies": {"http": proxy.url, "https": proxy.url}}


def test_youtubejs_bridge_receives_proxy_only_in_its_child_environment(monkeypatch, tmp_path) -> None:
    import yt_media_tools.youtubejs as backend

    captured = {}
    monkeypatch.setattr(backend.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(backend, "emit_invocation", lambda _invocation: None)

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(
            returncode=0,
            stderr="",
            stdout='{"ok":true,"id":"abc","title":"Title","channel_id":"channel"}\n',
        )

    monkeypatch.setattr(backend.subprocess, "run", fake_run)
    proxy = parse_proxy_url("socks5h://127.0.0.1:45678")

    backend.acquire_basic_info(tmp_path, ["abc"], proxy=proxy)

    assert captured["env"]["YT_DISCOVER_PROXY"] == proxy.url
