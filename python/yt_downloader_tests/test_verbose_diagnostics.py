"""Downloader verbose-plan and safe command diagnostics."""

from __future__ import annotations


def test_verbose_option_is_repeatable(downloader) -> None:
    parser = downloader.build_parser()

    assert parser.parse_args(["-v", "abc"]).verbose == 1
    assert parser.parse_args(["-vv", "abc"]).verbose == 2
    assert parser.parse_args(["--verbose", "--verbose", "abc"]).verbose == 2


def test_verbose_dry_run_keeps_command_on_stdout_and_diagnostics_on_stderr(downloader, capsys) -> None:
    assert downloader.main(["--dry-run", "-v", "abc"]) == 0

    captured = capsys.readouterr()
    assert "yt-dlp " in captured.out.splitlines()[0]
    assert "yt-download:" not in captured.out
    assert "yt-download: profile=" in captured.err
    assert "input=direct (1 target(s))" in captured.err
    assert "yt-download: yt-dlp command:" in captured.err


def test_double_verbose_reports_setting_provenance(downloader, capsys) -> None:
    assert downloader.main(["--dry-run", "-vv", "--resolution", "720", "abc"]) == 0

    captured = capsys.readouterr()
    assert "yt-download: setting resolution:" in captured.err


def test_normal_dry_run_remains_quiet_on_stderr(downloader, capsys) -> None:
    assert downloader.main(["--dry-run", "abc"]) == 0

    captured = capsys.readouterr()
    assert captured.out
    assert captured.err == ""


def test_verbose_normal_run_reports_the_command_that_is_executed(downloader, monkeypatch, capsys) -> None:
    executed = []
    monkeypatch.setattr(downloader, "validate_environment", lambda *, dry_run: "yt-dlp")

    def fake_run(command, *, dry_run):
        assert dry_run is False
        executed.append(list(command))
        return 0

    monkeypatch.setattr(downloader, "run", fake_run)

    assert downloader.main(["-v", "abc"]) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert executed and executed[0][-1] == "abc"
    assert downloader.format_diagnostic_command(executed[0]) in captured.err


def test_verbose_command_redacts_every_credential_bearing_surface(downloader) -> None:
    rendered = downloader.format_diagnostic_command(
        [
            "yt-dlp",
            "--cookies",
            "/secret/cookies.txt",
            "--proxy",
            "socks5h://user:proxy-secret@127.0.0.1:1080",
            "--add-headers",
            "Authorization:Bearer header-secret",
            "--extractor-args",
            "youtube:po_token=extractor-secret;player-client=web",
            "abc",
        ]
    )

    assert "cookies.txt" not in rendered
    assert "proxy-secret" not in rendered
    assert "header-secret" not in rendered
    assert "extractor-secret" not in rendered
    assert rendered.count("<redacted>") == 4
    assert "player-client=web" in rendered
