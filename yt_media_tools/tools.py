"""External tool discovery and capability reporting for yt-discover."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolStatus:
    """Availability and version information for one external capability."""

    name: str
    required: bool
    available: bool
    version: str | None = None
    detail: str = ""
    location: str | None = None


@dataclass(frozen=True)
class ToolRegistry:
    """External capabilities discovered before acquisition starts."""

    ytdlp: ToolStatus
    node: ToolStatus
    youtubejs: ToolStatus

    @property
    def youtubejs_available(self) -> bool:
        return self.node.available and self.youtubejs.available


def _run_version(command: list[str], *, cwd: Path | None = None) -> tuple[bool, str | None, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, None, str(exc)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
        return False, None, detail
    output = (result.stdout or result.stderr).strip().splitlines()
    return True, output[0].strip() if output else None, ""


def check_tools(project_root: Path) -> ToolRegistry:
    """Check required and optional acquisition tools without contacting YouTube."""
    ytdlp_path = shutil.which("yt-dlp")
    if ytdlp_path is None:
        ytdlp = ToolStatus("yt-dlp", True, False, detail="not found in PATH")
    else:
        ok, version, detail = _run_version([ytdlp_path, "--version"])
        ytdlp = ToolStatus("yt-dlp", True, ok, version=version, detail=detail)

    node_path = shutil.which("node")
    if node_path is None:
        node = ToolStatus("Node.js", False, False, detail="not found in PATH")
    else:
        ok, version, detail = _run_version([node_path, "--version"])
        node = ToolStatus("Node.js", False, ok, version=version, detail=detail)

    bridge = project_root / "yt_media_tools" / "youtubejs_bridge.mjs"
    if not node.available:
        youtubejs = ToolStatus(
            "YouTube.js",
            False,
            False,
            detail="Node.js is unavailable",
        )
    elif not bridge.is_file():
        youtubejs = ToolStatus(
            "YouTube.js",
            False,
            False,
            detail=f"bridge script is missing: {bridge}",
        )
    else:
        ok, output, detail = _run_version([node_path, str(bridge), "--check"], cwd=project_root)
        version = None
        location = None
        if ok and output:
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                ok = False
                detail = f"capability check returned invalid JSON: {output}"
            else:
                version = str(payload.get("version") or "unknown")
                location = payload.get("module_path")
                if location is not None:
                    location = str(location)
        if not ok and (
            "ERR_MODULE_NOT_FOUND" in detail
            or "Cannot find package 'youtubei.js'" in detail
            or "Cannot find module 'youtubei.js'" in detail
        ):
            detail = "youtubei.js could not be resolved by Node.js from the project environment"
        elif not ok and "\n" in detail:
            detail = detail.splitlines()[0]
        youtubejs = ToolStatus(
            "YouTube.js",
            False,
            ok,
            version=version,
            detail=detail,
            location=location,
        )

    return ToolRegistry(ytdlp=ytdlp, node=node, youtubejs=youtubejs)


def format_tool_check(registry: ToolRegistry) -> str:
    """Render a stable tool capability report."""

    def line(tool: ToolStatus) -> str:
        state = "available" if tool.available else "unavailable"
        suffix = f"  {tool.version}" if tool.version else ""
        return f"  {tool.name:<12} {state}{suffix}"

    lines = [
        "yt-discover tool check",
        "",
        "Required",
        line(registry.ytdlp),
        "",
        "Optional acquisition backend",
        line(registry.node),
        line(registry.youtubejs),
    ]
    for tool in (registry.ytdlp, registry.node, registry.youtubejs):
        if tool.available and tool.location:
            lines.append(f"    {tool.name}: resolved from {tool.location}")
        elif not tool.available and tool.detail:
            lines.append(f"    {tool.name}: {tool.detail}")

    lines.extend(["", "Available acquisition backends"])
    if registry.youtubejs_available:
        lines.append("  youtubejs  channel continuation enumeration")
    if registry.ytdlp.available:
        lines.append("  ytdlp      bounded and exhaustive acquisition")
    if registry.youtubejs_available and registry.ytdlp.available:
        lines.extend(
            [
                "",
                "Preferred automatic path",
                "  YouTube.js enumeration with yt-dlp detailed extraction",
                "",
                "Fallback policy",
                "  If YouTube.js fails in --backend auto, use yt-dlp bounded enumeration.",
            ]
        )
    elif registry.ytdlp.available:
        lines.extend(
            [
                "",
                "Preferred automatic path",
                "  yt-dlp enumeration and detailed extraction",
                "",
                "Fallback policy",
                "  YouTube.js is unavailable; --backend auto uses yt-dlp bounded enumeration.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Fallback policy",
                "  No acquisition fallback is available because required yt-dlp is unavailable.",
            ]
        )
    return "\n".join(lines)
