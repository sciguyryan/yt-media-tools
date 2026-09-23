"""yt-dlp command construction and completion-callback planning."""

from __future__ import annotations

from pathlib import Path


def test_build_command_contains_core_policy(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(resolution="1080", format_selector="bv+ba/best", reverse_playlist=True)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    assert command[0] == "yt-dlp"
    format_index = command.index("-f")
    assert command[format_index + 1] == "bv+ba/best"
    assert "--download-archive" in command
    assert str(downloader.ARCHIVE_FILE) in command
    assert "--cookies" not in command
    assert "--playlist-reverse" in command
    assert command[-1] == "abc"


def test_build_command_adds_after_move_callback_for_file_queue(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\n", encoding="utf-8")
    source = downloader.InputSource(batch_file=queue)
    policy = downloader.DownloadPolicy(resolution="1440", format_selector="bv+ba/best", reverse_playlist=False)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None, remove_completed_ids=True)
    exec_index = command.index("--exec")
    assert command[exec_index + 1].startswith("after_move:")
    assert "--_remove-completed-id" in command[exec_index + 1]
    assert command[-2:] == ["--batch-file", str(queue)]


def test_build_command_adds_explicit_cookies_file(downloader, tmp_path: Path) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(resolution="1080", format_selector="bv+ba/best", reverse_playlist=False)
    cookies = tmp_path / "cookies.txt"
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        source,
        None,
        cookies_file=cookies,
    )
    cookie_index = command.index("--cookies")
    assert command[cookie_index + 1] == str(cookies)


def test_build_command_adds_browser_cookies(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(
        resolution="1080",
        format_selector="bv+ba/best",
        reverse_playlist=False,
    )
    command = downloader.build_yt_dlp_command(
        "yt-dlp",
        policy,
        source,
        None,
        cookies_from_browser="firefox",
    )
    cookie_index = command.index("--cookies-from-browser")
    assert command[cookie_index + 1] == "firefox"
    assert "--cookies" not in command


def test_build_command_uses_annotated_row_targets_and_row_callback(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "annotated.txt"
    queue.write_text("abc # First title\ndef # Second title\n", encoding="utf-8")
    source = downloader.InputSource(batch_file=queue)
    policy = downloader.DownloadPolicy(resolution="1440", format_selector="bv+ba/best", reverse_playlist=False)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None, remove_completed_rows=True)
    exec_index = command.index("--exec")
    assert "--_remove-completed-row" in command[exec_index + 1]
    assert "--batch-file" not in command
    assert command[-2:] == ["abc", "def"]


def test_request_policy_compiles_to_documented_yt_dlp_options(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(
        resolution="1080",
        format_selector="bv+ba/best",
        reverse_playlist=False,
        user_agent="ExampleBrowser/1.0",
        referer="https://example.test/watch",
        headers=("X-Test:value", "Accept-Language:en-GB"),
        proxy="socks5://127.0.0.1:1080/",
        socket_timeout=12.5,
        source_address="192.0.2.10",
        ip_family="ipv4",
    )
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    header_values = [command[index + 1] for index, value in enumerate(command) if value == "--add-headers"]
    assert header_values == [
        "User-Agent:ExampleBrowser/1.0",
        "Referer:https://example.test/watch",
        "X-Test:value",
        "Accept-Language:en-GB",
    ]
    assert "--user-agent" not in command
    assert "--referer" not in command
    assert command[command.index("--proxy") + 1] == "socks5://127.0.0.1:1080/"
    assert command[command.index("--socket-timeout") + 1] == "12.5"
    assert command[command.index("--source-address") + 1] == "192.0.2.10"
    assert "--force-ipv4" in command
    assert "--force-ipv6" not in command


def test_request_policy_compiles_impersonation_target(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(
        resolution="1080",
        format_selector="bv+ba/best",
        reverse_playlist=False,
        impersonate="Firefox-147:Macos-26",
    )
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    index = command.index("--impersonate")
    assert command[index + 1] == "Firefox-147:Macos-26"
