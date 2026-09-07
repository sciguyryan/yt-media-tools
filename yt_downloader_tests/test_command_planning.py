"""yt-dlp command construction and completion-callback planning."""

from __future__ import annotations

from pathlib import Path


def test_build_command_contains_core_policy(downloader) -> None:
    source = downloader.InputSource(direct_targets=("abc",))
    policy = downloader.DownloadPolicy(resolution="1080", reverse_playlist=True)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None)
    assert command[0] == "yt-dlp"
    assert "--download-archive" in command
    assert str(downloader.ARCHIVE_FILE) in command
    assert "--cookies" in command
    assert str(downloader.COOKIES_FILE) in command
    assert "--playlist-reverse" in command
    assert command[-1] == "abc"


def test_build_command_adds_after_move_callback_for_file_queue(downloader, tmp_path: Path) -> None:
    queue = tmp_path / "ids.txt"
    queue.write_text("abc\n", encoding="utf-8")
    source = downloader.InputSource(batch_file=queue)
    policy = downloader.DownloadPolicy(resolution="1440", reverse_playlist=False)
    command = downloader.build_yt_dlp_command("yt-dlp", policy, source, None, remove_completed_ids=True)
    exec_index = command.index("--exec")
    assert command[exec_index + 1].startswith("after_move:")
    assert "--_remove-completed-id" in command[exec_index + 1]
    assert command[-2:] == ["--batch-file", str(queue)]
