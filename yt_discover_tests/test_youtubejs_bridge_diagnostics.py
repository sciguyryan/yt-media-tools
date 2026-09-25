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


def test_bridge_preserves_player_microformat_dates_without_promoting_them_to_normalised_dates() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "const microformat = info?.microformat || {};" in source
    assert "provider_native_dates:" in source
    assert "player_microformat_publish_date" in source
    assert "player_microformat_upload_date" in source
    assert "publish_date: basic.publish_date ?? null" in source
    assert "upload_date: basic.upload_date ?? null" in source


def test_bridge_can_compare_parsed_microformat_with_raw_player_response_without_promoting_dates() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "function rawPlayerMicroformatDates(payload)" in source
    assert "payload?.microformat?.playerMicroformatRenderer" in source
    assert "response_has_player_microformat" in source
    assert "response.clone().json()" in source
    assert "raw_player_response: rawPlayerResponseDates" in source
    assert "capture.reset();" in source
    assert "upload_date: basic.upload_date ?? null" in source
