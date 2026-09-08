"""Tests for source classification."""

import pytest

from yt_media_tools.sources import resolve_source


def test_channel_handle() -> None:
    spec = resolve_source("@example")
    assert spec.kind == "channel"
    assert spec.canonical_url == "https://www.youtube.com/@example"


def test_bare_name_is_channel() -> None:
    spec = resolve_source("example")
    assert spec.kind == "channel"


def test_channel_id() -> None:
    spec = resolve_source("UCabcdefghijklmnopqrstuv")
    assert spec.kind == "channel"
    assert "/channel/" in spec.canonical_url


def test_playlist_id() -> None:
    spec = resolve_source("PLabcdefghijklmnop")
    assert spec.kind == "playlist"
    assert "list=PLabcdefghijklmnop" in spec.canonical_url


def test_playlist_url() -> None:
    spec = resolve_source("https://www.youtube.com/playlist?list=PLabcdefghijklmnop")
    assert spec.kind == "playlist"


def test_watch_url_with_playlist_is_treated_as_playlist_collection() -> None:
    spec = resolve_source("https://www.youtube.com/watch?v=abc&list=PLabcdefghijklmnop")
    assert spec.kind == "playlist"


def test_playlist_rejects_tab() -> None:
    with pytest.raises(ValueError, match="--tab"):
        resolve_source("PLabcdefghijklmnop", tab="shorts")


def test_forced_playlist_accepts_unusual_id() -> None:
    spec = resolve_source("abcdefghijk", source_type="playlist")
    assert spec.kind == "playlist"


def test_generic_extractor_url_is_accepted_in_auto_mode() -> None:
    spec = resolve_source("https://www.twitch.tv/example/videos")
    assert spec.kind == "extractor"
    assert spec.canonical_url == "https://www.twitch.tv/example/videos"


def test_generic_extractor_url_rejects_youtube_tab_option() -> None:
    with pytest.raises(ValueError, match="does not advertise facet"):
        resolve_source("https://www.twitch.tv/example/videos", tab="videos")
