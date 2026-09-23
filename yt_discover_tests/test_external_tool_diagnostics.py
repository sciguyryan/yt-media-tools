from __future__ import annotations

import io

from yt_media_tools.external_tools import (
    ToolInvocation,
    configure_external_diagnostics,
    emit_invocation,
    format_invocation,
    registered_tools,
)


def test_registry_contains_current_external_integrations() -> None:
    identifiers = {tool.identifier for tool in registered_tools()}
    assert {"yt-dlp", "ffmpeg", "ffprobe", "node", "youtubejs", "graphviz", "newpipe-extractor"} <= identifiers


def test_command_diagnostics_redact_sensitive_arguments() -> None:
    configure_external_diagnostics(enabled=True)
    text = format_invocation(
        ToolInvocation(
            tool="yt-dlp",
            operation="download",
            purpose="media acquisition",
            argv=("yt-dlp", "--cookies", "/secret/cookies.txt", "--format", "best"),
        )
    )
    assert "/secret/cookies.txt" not in text
    assert "--cookies '<redacted>'" in text
    assert "--format best" in text


def test_library_diagnostics_are_annotated_without_fake_command_line() -> None:
    configure_external_diagnostics(enabled=True)
    text = format_invocation(
        ToolInvocation(
            tool="pytubefix",
            operation="YouTube",
            purpose="metadata acquisition",
            arguments={"url": "https://example.invalid/watch?v=x", "token": "secret"},
        )
    )
    assert "kind: python-library" in text
    assert "operation: YouTube" in text
    assert "token: <redacted>" in text
    assert "command:" not in text


def test_diagnostics_emit_only_when_enabled() -> None:
    stream = io.StringIO()
    invocation = ToolInvocation(tool="yt-dlp", operation="probe", purpose="test", argv=("yt-dlp", "--version"))
    configure_external_diagnostics(enabled=False, stream=stream)
    emit_invocation(invocation)
    assert stream.getvalue() == ""
    configure_external_diagnostics(enabled=True, stream=stream)
    emit_invocation(invocation)
    assert "[external] yt-dlp" in stream.getvalue()
