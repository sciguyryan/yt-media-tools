"""Architectural regression coverage for the thin Discover executable shell."""

from __future__ import annotations

import ast
from pathlib import Path

from yt_media_tools import discover_application, discover_cli
from yt_media_tools.retryable_http import configure_retryable_http_statuses


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-discover.py"


def test_executable_is_a_thin_application_shell() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert functions == []
    assert discover_application.main is not None


def test_cookie_override_is_parsed_as_path() -> None:
    parser = discover_cli.build_parser()
    args = parser.parse_args(["--cookies", "/tmp/example-cookies.txt", "@example"])
    assert args.cookies == Path("/tmp/example-cookies.txt")


def test_retryable_http_statuses_are_repeatable() -> None:
    parser = discover_cli.build_parser()
    args = parser.parse_args(["--retryable-http-status", "403", "--retryable-http-status", "429", "@example"])
    assert args.retryable_http_status == [403, 429]


def test_retryable_http_observation_uses_temporary_failure_exit(monkeypatch, capsys) -> None:
    def simulated_application(_argv):
        observer = configure_retryable_http_statuses((403, 429))
        observer.observe_text("ERROR: HTTP Error 429: Too Many Requests")
        return 0

    monkeypatch.setattr(discover_application, "_run_application", simulated_application)

    assert discover_application.main([]) == 75
    assert "retryable HTTP status observed: 429" in capsys.readouterr().err
    configure_retryable_http_statuses(())


def test_cache_compaction_is_an_explicit_introspection_mode() -> None:
    parser = discover_cli.build_parser()
    args = parser.parse_args(["--cache-compact"])
    assert args.cache_compact
    assert not args.cache_status


def test_cli_logic_lives_in_discover_cli_module() -> None:
    assert discover_cli.build_parser.__module__ == "yt_media_tools.discover_cli"
    assert discover_cli.parse_user_query.__module__ == "yt_media_tools.discover_cli"
    assert discover_cli.bind_query_parameters.__module__ == "yt_media_tools.discover_cli"


def test_parser_retains_established_programme_surface() -> None:
    parser = discover_cli.build_parser()
    option_strings = {option for action in parser._actions for option in action.option_strings}
    assert {
        "--examples",
        "--check-query",
        "--explain",
        "--explain-analyze",
        "--append",
        "--provenance",
        "--offline",
        "--param",
    } <= option_strings


def test_source_boundary_progress_label_distinguishes_facets() -> None:
    assert discover_application._source_boundary_label("@Insym", "videos") == "@Insym OF videos"
    assert discover_application._source_boundary_label("@Insym", "live") == "@Insym OF live"
    assert discover_application._source_boundary_label("@Insym", None) == "@Insym"
