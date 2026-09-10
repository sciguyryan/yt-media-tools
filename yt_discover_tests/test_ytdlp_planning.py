from pathlib import Path

from yt_media_tools.ytdlp import (
    DEFAULT_COOKIES_FILE,
    build_lazy_flat_command,
    build_metadata_command,
    build_video_metadata_command,
)


def test_lazy_flat_command_processes_playlist_incrementally():
    command = build_lazy_flat_command("https://www.youtube.com/@example/videos")
    assert "--flat-playlist" in command
    assert "--lazy-playlist" in command
    args = command[command.index("--extractor-args") + 1]
    assert "youtubetab:approximate_date" in args


def test_candidate_command_extracts_only_supplied_video_ids():
    command = build_video_metadata_command(["abc123XYZ00", "def456XYZ00"])
    assert "--no-playlist" in command
    assert command[-2:] == [
        "https://www.youtube.com/watch?v=abc123XYZ00",
        "https://www.youtube.com/watch?v=def456XYZ00",
    ]


def test_default_cookie_path_is_script_local():
    project_root = Path(__file__).resolve().parent.parent
    assert DEFAULT_COOKIES_FILE == project_root / "cookies.txt"


def test_metadata_command_uses_explicit_cookie_override(tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    command = build_metadata_command("https://www.youtube.com/@example/videos", cookies_file=cookies)
    cookie_index = command.index("--cookies")
    assert command[cookie_index + 1] == str(cookies)


def test_metadata_command_omits_missing_cookie_file(tmp_path):
    command = build_metadata_command(
        "https://www.youtube.com/@example/videos",
        cookies_file=tmp_path / "missing-cookies.txt",
    )
    assert "--cookies" not in command


def test_load_metadata_tolerates_fully_accounted_inaccessible_only_batch(tmp_path, monkeypatch) -> None:
    from yt_media_tools.ytdlp import load_metadata

    fake = tmp_path / "yt-dlp"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('ERROR: [youtube] 58x8FebkTSA: Join this channel to get access to members-only content like this video, and other exclusive perks.', file=sys.stderr)\n"
        "print('ERROR: [youtube] Dxnr0nRCq8M: This video is private', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + __import__("os").pathsep + __import__("os").environ.get("PATH", ""))

    records, stats = load_metadata(["yt-dlp", "dummy"])

    assert records == []
    assert stats.available == 0
    assert stats.skipped == 2
    assert stats.skipped_by_id["58x8FebkTSA"] == "members-only"
    assert stats.skipped_by_id["Dxnr0nRCq8M"] == "private"


def test_load_metadata_keeps_unexplained_nonzero_exit_fatal(tmp_path, monkeypatch) -> None:
    import pytest
    from yt_media_tools.ytdlp import YtDlpError, load_metadata

    fake = tmp_path / "yt-dlp"
    fake.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('ERROR: unable to initialise extractor', file=sys.stderr)\n"
        "raise SystemExit(1)\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + __import__("os").pathsep + __import__("os").environ.get("PATH", ""))

    with pytest.raises(YtDlpError, match=r"yt-dlp exited with status 1"):
        load_metadata(["yt-dlp", "dummy"])
