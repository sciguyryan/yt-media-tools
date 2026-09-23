from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark_metadata_providers.py"


def _module():
    spec = importlib.util.spec_from_file_location("metadata_provider_benchmark", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_script_runs_directly_from_repository_root() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--youtubejs-cookies" in result.stdout


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


class _FakeCaptions:
    def __iter__(self):
        return iter(("en", "de"))


class _FakePytubefixVideo:
    title = "Example"
    description = "Description"
    channel_id = "UCexample"
    length = 123
    views = 456
    keywords = ["one", "two"]
    thumbnail_url = "https://example.invalid/thumb.jpg"
    chapters = [{"title": "Intro"}, {"title": "End"}]
    captions = _FakeCaptions()
    vid_info = {
        "playabilityStatus": {"status": "OK"},
        "videoDetails": {"isPrivate": False, "isLiveContent": True, "videoId": "abc"},
    }

    class _Date:
        @staticmethod
        def strftime(pattern):
            assert pattern == "%Y%m%d"
            return "20260922"

    publish_date = _Date()


def test_pytubefix_is_available_as_experimental_provider() -> None:
    benchmark = _module()
    assert "pytubefix" in benchmark.PROVIDERS
    assert benchmark._provider_names("pytubefix") == ["pytubefix", "ytdlp"]


def test_pytubefix_normalisation_keeps_extended_capabilities_separate() -> None:
    benchmark = _module()
    row = benchmark._normalise_pytubefix("abc", _FakePytubefixVideo(), include_extended=True)
    assert row["id"] == "abc"
    assert row["title"] == "Example"
    assert row["channel_id"] == "UCexample"
    assert row["duration"] == 123
    assert row["view_count"] == 456
    assert row["upload_date"] == "20260922"
    assert row["category"] is None
    assert row["is_live"] is None
    assert row["keywords"] == ["one", "two"]
    assert row["source_signals"]["playability_status"] == "OK"
    assert row["source_signals"]["is_live_content"] is True
    assert row["extended_capabilities"] == {
        "thumbnail_url": {"available": True},
        "chapters": {"available": True, "count": 2},
        "captions": {"available": True, "count": 2, "codes": ["de", "en"]},
    }


def test_pytubefix_capability_probe_failure_does_not_discard_core_metadata() -> None:
    benchmark = _module()

    class BrokenCapabilities(_FakePytubefixVideo):
        @property
        def chapters(self):
            raise RuntimeError("chapter endpoint unavailable")

    row = benchmark._normalise_pytubefix("abc", BrokenCapabilities(), include_extended=True)
    assert row["ok"] is True
    assert row["extended_capabilities"]["chapters"] == {"available": False, "error_type": "RuntimeError"}


def test_pytubefix_runner_records_per_video_failures(monkeypatch) -> None:
    benchmark = _module()

    class FakeModule:
        __version__ = "test-version"

        @staticmethod
        def YouTube(url):
            if url.endswith("private-id"):
                raise RuntimeError("Private video")
            return _FakePytubefixVideo()

    original_import = benchmark.importlib.import_module
    monkeypatch.setattr(
        benchmark.importlib,
        "import_module",
        lambda name: FakeModule if name == "pytubefix" else original_import(name),
    )
    rows, _, diagnostics = benchmark._pytubefix(["ok-id", "private-id"])
    assert rows[0]["ok"] is True
    assert rows[1]["failure"]["kind"] == "private"
    assert diagnostics["version"] == "test-version"
    assert diagnostics["authentication"] == "anonymous"
    assert diagnostics["network_measurement"] == "not instrumented"


def test_core_profile_does_not_probe_pytubefix_extended_capabilities() -> None:
    benchmark = _module()

    class CoreOnlyVideo(_FakePytubefixVideo):
        @property
        def thumbnail_url(self):
            raise AssertionError("core profile probed thumbnail metadata")

        @property
        def chapters(self):
            raise AssertionError("core profile probed chapter metadata")

        @property
        def captions(self):
            raise AssertionError("core profile probed caption metadata")

    row = benchmark._normalise_pytubefix("abc", CoreOnlyVideo(), include_extended=False)
    assert row["extended_capabilities"] == {"status": "not_requested"}


def test_measurement_profile_support_is_explicit() -> None:
    benchmark = _module()
    assert benchmark.PROFILE_SUPPORT["youtubejs"] == {"core"}
    assert benchmark.PROFILE_SUPPORT["youtube-innertube"] == {"core"}
    assert benchmark.PROFILE_SUPPORT["pytubefix"] == {"core", "full"}
    assert benchmark.PROFILE_SUPPORT["invidious"] == {"core"}
    assert benchmark.PROFILE_SUPPORT["ytdlp"] == {"core", "full"}


def test_full_ytdlp_inventory_is_structural_only() -> None:
    benchmark = _module()
    row = benchmark._normalise_ytdlp(
        {
            "id": "abc",
            "thumbnails": [{"url": "https://secret.example/thumb.jpg"}],
            "chapters": [{"title": "Intro"}],
            "subtitles": {"en": [{"url": "https://secret.example/en.vtt"}]},
            "automatic_captions": {"cy": [{"url": "https://secret.example/cy.vtt"}]},
        },
        include_extended=True,
    )
    assert row["extended_capabilities"] == {
        "thumbnail_url": {"available": True},
        "chapters": {"available": True, "count": 1},
        "captions": {"available": True, "count": 2, "codes": ["cy", "en"]},
    }
    assert "secret.example" not in str(row["extended_capabilities"])


def test_newpipe_extractor_is_available_as_experimental_provider() -> None:
    benchmark = _module()
    assert "newpipe-extractor" in benchmark.PROVIDERS
    assert benchmark._provider_names("newpipe-extractor") == ["newpipe-extractor", "ytdlp"]
    assert benchmark.PROFILE_SUPPORT["newpipe-extractor"] == {"core"}


def test_newpipe_normalisation_preserves_bridge_signals_separately() -> None:
    benchmark = _module()
    row = benchmark._normalise_newpipe(
        {
            "id": "abc",
            "ok": True,
            "title": "Example",
            "description": "Description",
            "uploader_name": "Example channel",
            "uploader_url": "https://www.youtube.com/channel/UCexample",
            "duration": 123,
            "view_count": 456,
            "upload_date": "2026-09-23T12:34:56Z",
            "upload_date_approximate": False,
            "category": "Science & Technology",
            "stream_type": "VIDEO_STREAM",
            "keywords": ["one", "two"],
            "content_availability": "PUBLIC",
            "uploader_verified": True,
            "short_form": False,
            "elapsed_ms": 12.5,
        }
    )
    assert row["channel_id"] == "UCexample"
    assert row["upload_date"] == "20260923"
    assert row["is_live"] is False
    assert row["elapsed_ms"] == 12.5
    assert row["source_signals"]["content_availability"] == "PUBLIC"
    assert row["source_signals"]["uploader_verified"] is True


def test_newpipe_failure_is_classified_without_discarding_error_type() -> None:
    benchmark = _module()
    row = benchmark._normalise_newpipe(
        {"id": "private-id", "ok": False, "error_type": "ContentNotAvailableException", "error": "Private video"}
    )
    assert row["failure"]["kind"] == "private"
    assert row["failure"]["error_type"] == "ContentNotAvailableException"


def test_newpipe_runner_keeps_one_jvm_for_the_corpus(monkeypatch, tmp_path) -> None:
    benchmark = _module()
    bridge = tmp_path / "newpipe-bridge"
    bridge.write_text("stub", encoding="utf-8")
    monkeypatch.setenv(benchmark.NEWPIPE_BRIDGE_ENV, str(bridge))
    calls = []

    def fake_json_lines(command, *, env=None):
        calls.append(command)
        return ([{"id": "a", "ok": True, "elapsed_ms": 10.0}, {"id": "b", "ok": True, "elapsed_ms": 20.0}], 0.05, "")

    monkeypatch.setattr(benchmark, "_json_lines", fake_json_lines)
    rows, elapsed, diagnostics = benchmark._newpipe_extractor(["a", "b"])
    assert calls == [[str(bridge), "a", "b"]]
    assert len(rows) == 2
    assert elapsed == 0.05
    assert diagnostics["jvm_processes"] == 1
    assert diagnostics["per_item_elapsed_ms"] == [10.0, 20.0]
    assert diagnostics["startup_and_shutdown_ms"] == 20.0


def test_description_analysis_distinguishes_markup_from_text() -> None:
    benchmark = _module()
    result = benchmark._description_analysis(
        {"description": "E&amp;L<br><b>computer</b>"},
        {"description": "E&L computer"},
    )
    assert result["status"] == "text_equal"
    assert result["text_equal"] is True
    assert result["similarity_ratio"] == 1.0


def test_description_analysis_reports_similarity_without_claiming_equivalence() -> None:
    benchmark = _module()
    result = benchmark._description_analysis(
        {"description": '<a href="https://example.invalid/full">https://example.invalid/...</a>'},
        {"description": "https://example.invalid/full"},
    )
    assert result["status"] == "different"
    assert result["text_equal"] is False
    assert 0.0 < result["similarity_ratio"] < 1.0


def test_issue_109_heterogeneous_corpus_is_deterministic_and_diverse() -> None:
    import json

    corpus = json.loads((ROOT / "benchmarks/metadata-provider-corpora/issue-109-heterogeneous.json").read_text())
    ids = [item["id"] for item in corpus["items"]]
    traits = {trait for item in corpus["items"] for trait in item["traits"]}
    assert corpus["schema_version"] == 1
    assert len(ids) == len(set(ids)) >= 8
    assert {"very-old-upload", "short-form-candidate", "live-history", "non-english-title"} <= traits


def test_benchmark_video_id_rejects_whitespace() -> None:
    benchmark = _module()
    try:
        benchmark._video_id("first second")
    except benchmark.argparse.ArgumentTypeError as exc:
        assert str(exc) == "video ID must not contain whitespace"
    else:
        raise AssertionError("whitespace-containing benchmark ID was accepted")


def test_newpipe_stderr_is_hidden_by_default_and_available_on_demand(monkeypatch, tmp_path, capsys) -> None:
    benchmark = _module()
    bridge = tmp_path / "newpipe-bridge"
    bridge.write_text("bridge")
    monkeypatch.setattr(benchmark, "_newpipe_bridge_path", lambda: bridge)
    monkeypatch.setattr(
        benchmark,
        "_json_lines",
        lambda command: ([{"id": "abc", "ok": True, "elapsed_ms": 1.0}], 0.01, "diagnostic chatter\n"),
    )

    benchmark._newpipe_extractor(["abc"])
    assert capsys.readouterr().err == ""

    monkeypatch.setenv(benchmark.NEWPIPE_DIAGNOSTICS_ENV, "1")
    benchmark._newpipe_extractor(["abc"])
    stderr = capsys.readouterr().err
    assert "[NewPipeExtractor bridge stderr]" in stderr
    assert "diagnostic chatter" in stderr


def test_invidious_is_explicit_core_only_provider() -> None:
    benchmark = _module()
    assert "invidious" in benchmark.PROVIDERS
    assert benchmark._provider_names("invidious") == ["invidious", "ytdlp"]
    assert benchmark.PROFILE_SUPPORT["invidious"] == {"core"}
    assert "invidious" not in benchmark.DEFAULT_PROVIDERS


def test_invidious_instance_validation_requires_explicit_absolute_url() -> None:
    benchmark = _module()
    assert benchmark._invidious_instance("https://inv.example/") == "https://inv.example"
    for value in ("inv.example", "ftp://inv.example", "https://user:secret@inv.example", "https://inv.example/?x=1"):
        try:
            benchmark._invidious_instance(value)
        except benchmark.argparse.ArgumentTypeError:
            pass
        else:
            raise AssertionError(f"unsafe or ambiguous Invidious instance accepted: {value}")


def test_invidious_normalisation_preserves_live_and_provider_signals() -> None:
    benchmark = _module()
    row = benchmark._normalise_invidious(
        "abc",
        {
            "videoId": "abc",
            "title": "Example",
            "description": "Description",
            "author": "Channel",
            "authorId": "UCexample",
            "authorUrl": "/channel/UCexample",
            "lengthSeconds": 123,
            "viewCount": 456,
            "published": 0,
            "genre": "Science & Technology",
            "liveNow": False,
            "isPostLiveDvr": True,
            "isUpcoming": False,
            "isListed": True,
            "keywords": ["one"],
        },
    )
    assert row["channel_id"] == "UCexample"
    assert row["upload_date"] == "19700101"
    assert row["duration"] == 123
    assert row["is_live"] is False
    assert row["source_signals"]["is_post_live_dvr"] is True


def test_invidious_requires_configuration_before_any_request(monkeypatch) -> None:
    benchmark = _module()
    monkeypatch.delenv(benchmark.INVIDIOUS_INSTANCE_ENV, raising=False)
    try:
        benchmark._invidious(["abc"])
    except RuntimeError as exc:
        assert "explicitly configured instance" in str(exc)
    else:
        raise AssertionError("Invidious provider ran without an explicitly configured instance")


def test_invidious_runner_uses_only_selected_instance(monkeypatch) -> None:
    benchmark = _module()
    requested = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.payload

    def fake_urlopen(request, timeout):
        requested.append((request.full_url, timeout))
        if request.full_url.endswith("/api/v1/stats"):
            return FakeResponse(b'{"software":{"name":"invidious"}}')
        return FakeResponse(b'{"videoId":"abc","title":"Example","published":0,"liveNow":false}')

    monkeypatch.setattr(benchmark, "urlopen", fake_urlopen)
    rows, _, diagnostics = benchmark._invidious(["abc"], instance="https://chosen.example/")
    assert requested == [
        ("https://chosen.example/api/v1/stats", benchmark.INVIDIOUS_PREFLIGHT_TIMEOUT_SECONDS),
        ("https://chosen.example/api/v1/videos/abc", benchmark.INVIDIOUS_REQUEST_TIMEOUT_SECONDS),
    ]
    assert rows[0]["id"] == "abc"
    assert diagnostics["instance"] == "https://chosen.example"
    assert diagnostics["request_count"] == 1


def test_invidious_preflight_fails_before_video_requests(monkeypatch) -> None:
    benchmark = _module()
    requested = []

    def fake_urlopen(request, timeout):
        requested.append((request.full_url, timeout))
        raise TimeoutError("timed out")

    monkeypatch.setattr(benchmark, "urlopen", fake_urlopen)
    try:
        benchmark._invidious(["abc", "def"], instance="https://unreachable.example/")
    except RuntimeError as exc:
        assert "preflight failed" in str(exc)
        assert "unreachable.example" in str(exc)
    else:
        raise AssertionError("unreachable Invidious instance passed preflight")
    assert requested == [("https://unreachable.example/api/v1/stats", benchmark.INVIDIOUS_PREFLIGHT_TIMEOUT_SECONDS)]
