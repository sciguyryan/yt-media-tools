from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "yt_media_tools" / "youtubejs_bridge.mjs"


def test_bridge_filters_only_named_routine_parser_warning_and_has_diagnostic_escape_hatch() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "[YOUTUBEJS][Text]: Unable to find matching run for attachment run. Skipping" in source
    assert "YT_DISCOVER_YOUTUBEJS_DIAGNOSTICS" in source
    assert "console.warn =" in source
    assert "console.error =" not in source
    assert "process.stderr.write(`[yt-discover:youtubejs] ${message}\\n`)" in source
