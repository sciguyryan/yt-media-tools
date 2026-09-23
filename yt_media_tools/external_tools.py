"""Structured diagnostics for external tools and library integrations."""

from __future__ import annotations

from dataclasses import dataclass
import shlex
import sys
from typing import Any, Mapping, Sequence, TextIO


@dataclass(frozen=True)
class ExternalTool:
    """Descriptive registration for one external integration."""

    identifier: str
    display_name: str
    kind: str


@dataclass(frozen=True)
class ToolInvocation:
    """One planned or executing operation against a registered integration."""

    tool: str
    operation: str
    purpose: str
    status: str = "executing"
    argv: tuple[str, ...] | None = None
    arguments: Mapping[str, Any] | None = None


_TOOLS: dict[str, ExternalTool] = {
    tool.identifier: tool
    for tool in (
        ExternalTool("yt-dlp", "yt-dlp", "command"),
        ExternalTool("ffmpeg", "FFmpeg", "command"),
        ExternalTool("ffprobe", "ffprobe", "command"),
        ExternalTool("node", "Node.js", "command"),
        ExternalTool("youtubejs", "YouTube.js", "bridge"),
        ExternalTool("graphviz", "Graphviz", "command"),
        ExternalTool("pytubefix", "pytubefix", "python-library"),
        ExternalTool("youtube-innertube", "youtube-innertube", "python-library"),
        ExternalTool("newpipe-extractor", "NewPipeExtractor", "jvm-bridge"),
    )
}

_enabled = False
_unsafe = False
_stream: TextIO = sys.stderr

_SENSITIVE_OPTIONS = {
    "--cookies",
    "--cookies-from-browser",
    "--username",
    "--password",
    "--video-password",
    "--ap-mso",
    "--ap-username",
    "--ap-password",
    "--client-certificate",
    "--client-certificate-key",
    "--client-certificate-password",
}
_SENSITIVE_ARGUMENT_NAMES = {"cookie", "cookies", "password", "token", "authorization", "headers"}


def registered_tools() -> tuple[ExternalTool, ...]:
    """Return the stable external-integration catalogue."""
    return tuple(_TOOLS[key] for key in sorted(_TOOLS))


def configure_external_diagnostics(*, enabled: bool, unsafe: bool = False, stream: TextIO | None = None) -> None:
    """Configure process-wide external invocation diagnostics for one CLI run."""
    global _enabled, _unsafe, _stream
    _enabled = enabled or unsafe
    _unsafe = unsafe
    _stream = stream if stream is not None else sys.stderr


def _redact_argv(argv: Sequence[str]) -> list[str]:
    if _unsafe:
        return list(argv)
    rendered: list[str] = []
    redact_next = False
    for value in argv:
        if redact_next:
            rendered.append("<redacted>")
            redact_next = False
            continue
        rendered.append(value)
        if value in _SENSITIVE_OPTIONS or value == "--proxy":
            redact_next = True
        elif value.startswith("--add-headers=") and any(
            name in value.casefold() for name in ("authorization:", "cookie:")
        ):
            rendered[-1] = value.split("=", 1)[0] + "=<redacted>"
    return rendered


def _redact_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    if _unsafe:
        return dict(arguments)
    return {
        key: "<redacted>" if key.casefold() in _SENSITIVE_ARGUMENT_NAMES else value for key, value in arguments.items()
    }


def format_invocation(invocation: ToolInvocation) -> str:
    """Render one invocation deterministically with safe redaction by default."""
    tool = _TOOLS.get(invocation.tool, ExternalTool(invocation.tool, invocation.tool, "external"))
    lines = [
        f"[external] {tool.display_name}",
        f"kind: {tool.kind}",
        f"purpose: {invocation.purpose}",
        f"operation: {invocation.operation}",
        f"status: {invocation.status}",
    ]
    if invocation.argv is not None:
        lines.append(f"command: {shlex.join(_redact_argv(invocation.argv))}")
    if invocation.arguments is not None:
        lines.append("arguments:")
        for key, value in sorted(_redact_arguments(invocation.arguments).items()):
            lines.append(f"  {key}: {value}")
    return "\n".join(lines)


def emit_invocation(invocation: ToolInvocation) -> None:
    """Emit one invocation when external diagnostics are enabled."""
    if not _enabled:
        return
    print(format_invocation(invocation), file=_stream)
