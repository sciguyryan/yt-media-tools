from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_metadata_providers.py"


def _module():
    spec = importlib.util.spec_from_file_location("metadata_provider_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_comparison_covers_issue_103_scalar_surface() -> None:
    benchmark = _module()
    assert benchmark.COMPARISON_FIELDS == (
        "id",
        "title",
        "description",
        "channel_id",
        "duration",
        "view_count",
        "upload_date",
        "category",
        "is_live",
        "keywords",
    )


def test_youtube_innertube_normalisation_is_explicit() -> None:
    benchmark = _module()
    assert benchmark._normalise_youtube_innertube(
        "abc",
        {
            "title": "Title",
            "description": "Description",
            "channelId": "chan",
            "durationSeconds": 42,
            "viewCount": 7,
            "publishDate": "2026-09-22",
            "category": "Science & Technology",
            "isLive": False,
            "keywords": ["one", "two"],
        },
    ) == {
        "id": "abc",
        "title": "Title",
        "description": "Description",
        "channel_id": "chan",
        "duration": 42,
        "view_count": 7,
        "upload_date": "2026-09-22",
        "category": "Science & Technology",
        "is_live": False,
        "keywords": ["one", "two"],
        "ok": True,
    }


def test_agreement_does_not_treat_presence_as_equivalence() -> None:
    benchmark = _module()
    result = benchmark._agreement(
        {"id": "abc", "title": "Title", "upload_date": "2026-09-22", "keywords": ["one"]},
        {"id": "abc", "title": "Title", "upload_date": "20260922", "keywords": ["different"]},
    )
    assert result["id"] == "equal"
    assert result["title"] == "equal"
    assert result["upload_date"] == "different"
    assert result["keywords"] == "different"
    assert result["duration"] == "missing"


def test_provider_parser_always_includes_ytdlp_reference() -> None:
    benchmark = _module()
    assert benchmark._provider_names("youtube-innertube") == ["youtube-innertube", "ytdlp"]
    assert benchmark._provider_names("youtubejs,ytdlp") == ["youtubejs", "ytdlp"]
