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
        "source_signals": {
            "isLive": False,
            "available_keys": [
                "category",
                "channelId",
                "description",
                "durationSeconds",
                "isLive",
                "keywords",
                "publishDate",
                "title",
                "viewCount",
            ],
        },
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


def test_view_count_difference_records_absolute_and_relative_delta() -> None:
    benchmark = _module()
    result = benchmark._comparison(
        "abc",
        {"id": "abc", "view_count": 1005, "ok": True},
        {"id": "abc", "view_count": 1000, "ok": True},
    )
    assert result["agreement"]["view_count"] == "different"
    assert result["deltas"]["view_count"] == {
        "candidate": 1005,
        "reference": 1000,
        "absolute": 5,
        "relative_percent": 0.5,
    }


def test_equal_or_missing_view_count_does_not_emit_delta() -> None:
    benchmark = _module()
    equal = benchmark._comparison(
        "abc", {"id": "abc", "view_count": 1000, "ok": True}, {"id": "abc", "view_count": 1000}
    )
    missing = benchmark._comparison(
        "abc", {"id": "abc", "view_count": None, "ok": True}, {"id": "abc", "view_count": 1000}
    )
    assert equal["deltas"] == {}
    assert missing["deltas"] == {}


def test_zero_reference_view_count_has_no_relative_percentage() -> None:
    benchmark = _module()
    result = benchmark._comparison("abc", {"id": "abc", "view_count": 1, "ok": True}, {"id": "abc", "view_count": 0})
    assert result["deltas"]["view_count"]["absolute"] == 1
    assert result["deltas"]["view_count"]["relative_percent"] is None


def test_failure_classification_distinguishes_adversarial_outcomes() -> None:
    benchmark = _module()
    assert benchmark._classify_failure("Private video") == "private"
    assert benchmark._classify_failure("This video has been removed for violating YouTube policy") == "removed"
    assert (
        benchmark._classify_failure("HTTP Error 429: Too Many Requests; Sign in to confirm you're not a bot")
        == "rate_limited"
    )
    assert benchmark._classify_failure("Sign in to confirm your age") == "authentication_required"
    assert benchmark._classify_failure("This video is unavailable") == "unavailable"
    assert benchmark._classify_failure("unexpected backend response") == "provider_error"


def test_failed_comparison_records_which_side_failed() -> None:
    benchmark = _module()
    candidate_failure = benchmark._failure_row("abc", "This video is unavailable")
    reference_failure = benchmark._failure_row("abc", "Private video")
    candidate_only = benchmark._comparison("abc", candidate_failure, {"id": "abc", "ok": True})
    reference_only = benchmark._comparison("abc", {"id": "abc", "ok": True}, reference_failure)
    both = benchmark._comparison("abc", candidate_failure, reference_failure)
    assert candidate_only["status"] == "candidate_failed"
    assert candidate_only["candidate_failure"]["kind"] == "unavailable"
    assert reference_only["status"] == "reference_failed"
    assert reference_only["reference_failure"]["kind"] == "private"
    assert both["status"] == "both_failed"
    assert both["agreement"] == {}


def test_provider_summary_counts_failure_kinds() -> None:
    benchmark = _module()
    rows = [
        {"id": "ok", "ok": True},
        benchmark._failure_row("private", "Private video"),
        benchmark._failure_row("missing", "This video is unavailable"),
    ]
    assert benchmark._provider_summary(rows, 3) == {
        "expected": 3,
        "reported": 3,
        "succeeded": 1,
        "failed": 2,
        "failures_by_kind": {"private": 1, "unavailable": 1},
    }


def test_youtubejs_failure_preserves_structured_diagnostic() -> None:
    benchmark = _module()
    row = benchmark._normalise_youtubejs({"id": "abc", "ok": False, "error": "This video is unavailable"})
    assert row["ok"] is False
    assert row["failure"]["kind"] == "unavailable"
    assert row["failure"]["message"] == "This video is unavailable"


def test_ytdlp_diagnostics_are_associated_with_failed_video_ids() -> None:
    benchmark = _module()
    stderr = "\n".join(
        (
            "WARNING: [youtube] first_id: Unable to download webpage: HTTP Error 429: Too Many Requests",
            "ERROR: [youtube] first_id: Sign in to confirm you’re not a bot",
            "ERROR: [youtube] second_id: Private video",
        )
    )
    result = benchmark._ytdlp_diagnostics_by_id(stderr, ["first_id", "second_id", "successful_id"])
    assert "HTTP Error 429" in result["first_id"]
    assert "not a bot" in result["first_id"]
    assert result["second_id"] == "ERROR: [youtube] second_id: Private video"
    assert "successful_id" not in result


def test_youtubejs_normalisation_preserves_playability_and_live_signals() -> None:
    benchmark = _module()
    row = benchmark._normalise_youtubejs(
        {
            "id": "private-id",
            "ok": True,
            "title": None,
            "is_live": False,
            "is_live_content": False,
            "is_private": True,
            "is_unlisted": False,
            "playability_status": "LOGIN_REQUIRED",
        }
    )
    assert row["source_signals"] == {
        "is_live": False,
        "is_live_content": False,
        "is_private": True,
        "is_unlisted": False,
        "playability_status": "LOGIN_REQUIRED",
    }


def test_youtube_innertube_normalisation_preserves_live_signal_and_available_keys() -> None:
    benchmark = _module()
    row = benchmark._normalise_youtube_innertube(
        "live-id",
        {
            "title": "Archived stream",
            "isLive": True,
            "viewCount": 10,
            "unexpectedLiveHint": "ended",
        },
    )
    assert row["source_signals"]["isLive"] is True
    assert row["source_signals"]["available_keys"] == ["isLive", "title", "unexpectedLiveHint", "viewCount"]


def test_ytdlp_normalisation_preserves_reference_live_and_availability_signals() -> None:
    benchmark = _module()
    row = benchmark._normalise_ytdlp(
        {
            "id": "archived-id",
            "is_live": False,
            "was_live": True,
            "live_status": "was_live",
            "availability": "public",
        }
    )
    assert row["source_signals"] == {
        "is_live": False,
        "was_live": True,
        "live_status": "was_live",
        "availability": "public",
    }


def test_youtubejs_cookie_requires_environment_value(monkeypatch) -> None:
    benchmark = _module()
    monkeypatch.delenv(benchmark.YOUTUBEJS_COOKIE_ENV, raising=False)
    assert benchmark._youtubejs_cookie_from_environment(False) is None
    try:
        benchmark._youtubejs_cookie_from_environment(True)
    except RuntimeError as exc:
        assert benchmark.YOUTUBEJS_COOKIE_ENV in str(exc)
    else:
        raise AssertionError("missing cookie environment value was accepted")


def test_youtubejs_cookie_is_read_from_environment(monkeypatch) -> None:
    benchmark = _module()
    monkeypatch.setenv(benchmark.YOUTUBEJS_COOKIE_ENV, "SID=secret; HSID=other")
    assert benchmark._youtubejs_cookie_from_environment(True) == "SID=secret; HSID=other"


def test_secret_guard_rejects_cookie_material_anywhere_in_report() -> None:
    benchmark = _module()
    secret = "SID=super-secret-cookie"
    benchmark._assert_secrets_absent({"safe": "anonymous"}, (secret,))
    try:
        benchmark._assert_secrets_absent({"failure": {"message": f"backend echoed {secret}"}}, (secret,))
    except RuntimeError as exc:
        assert "refusing to serialise" in str(exc)
    else:
        raise AssertionError("credential material was allowed into serialisable output")


def test_youtubejs_runner_passes_cookie_only_through_child_environment(monkeypatch) -> None:
    benchmark = _module()
    captured = {}
    monkeypatch.setattr(benchmark.shutil, "which", lambda name: "/usr/bin/node")

    def fake_json_lines(command, *, env=None):
        captured["command"] = command
        captured["env"] = env
        return [{"id": "abc", "ok": True}], 0.1, ""

    monkeypatch.setattr(benchmark, "_json_lines", fake_json_lines)
    _, _, diagnostics = benchmark._youtubejs(["abc"], cookie="SID=secret")
    assert "SID=secret" not in captured["command"]
    assert captured["env"][benchmark.YOUTUBEJS_COOKIE_ENV] == "SID=secret"
    assert diagnostics["authentication"] == "cookie"


def test_anonymous_youtubejs_runner_removes_inherited_cookie(monkeypatch) -> None:
    benchmark = _module()
    captured = {}
    monkeypatch.setenv(benchmark.YOUTUBEJS_COOKIE_ENV, "SID=inherited")
    monkeypatch.setattr(benchmark.shutil, "which", lambda name: "/usr/bin/node")

    def fake_json_lines(command, *, env=None):
        captured["env"] = env
        return [{"id": "abc", "ok": True}], 0.1, ""

    monkeypatch.setattr(benchmark, "_json_lines", fake_json_lines)
    _, _, diagnostics = benchmark._youtubejs(["abc"])
    assert benchmark.YOUTUBEJS_COOKIE_ENV not in captured["env"]
    assert diagnostics["authentication"] == "anonymous"


def test_redaction_removes_cookie_header_and_individual_values() -> None:
    benchmark = _module()
    header = "SID=super-secret; HSID=other-secret"
    payload = {"failure": {"message": f"invalid header {header}; value super-secret"}}
    redacted = benchmark._redact_secrets(payload, (header, "super-secret", "other-secret"))
    serialised = str(redacted)
    assert "super-secret" not in serialised
    assert "other-secret" not in serialised
    assert "[REDACTED]" in serialised


def test_secret_guard_checks_multiple_cookie_values() -> None:
    benchmark = _module()
    try:
        benchmark._assert_secrets_absent({"message": "leaked secret-two"}, ("header", "secret-one", "secret-two"))
    except RuntimeError as exc:
        assert "refusing to serialise" in str(exc)
    else:
        raise AssertionError("individual cookie value was allowed into serialisable output")
