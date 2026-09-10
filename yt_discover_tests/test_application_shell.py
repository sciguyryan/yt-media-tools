"""Architectural regression coverage for the thin Discover executable shell."""

from __future__ import annotations

import ast
from pathlib import Path

from yt_media_tools import discover_application, discover_cli


ROOT = Path(__file__).resolve().parents[1]
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


def test_cli_logic_lives_in_discover_cli_module() -> None:
    assert discover_cli.build_parser.__module__ == "yt_media_tools.discover_cli"
    assert discover_cli.parse_user_query.__module__ == "yt_media_tools.discover_cli"
    assert discover_cli.bind_query_parameters.__module__ == "yt_media_tools.discover_cli"


def test_parser_retains_established_programme_surface() -> None:
    parser = discover_cli.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
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
