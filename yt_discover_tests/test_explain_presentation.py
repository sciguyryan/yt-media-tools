"""Deterministic explain presentation and renderer contracts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from yt_media_tools.discover_explain import explain_user_query, explain_user_query_json
from yt_media_tools.explain_presentation import (
    EXPLANATION_SCHEMA_VERSION,
    build_explain_graph,
    graph_to_dot,
    render_console_overview,
    resolve_console_modes,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


class _Stream:
    """Small deterministic terminal capability stub."""

    def __init__(self, *, tty: bool, encoding: str = "utf-8") -> None:
        self._tty = tty
        self.encoding = encoding

    def isatty(self) -> bool:
        return self._tty


def test_json_explain_has_versioned_decision_and_graph_model() -> None:
    payload = explain_user_query_json(
        "SELECT duration FROM @example WHERE title = 'x' LIMIT 5",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    assert payload["schema_version"] == EXPLANATION_SCHEMA_VERSION
    explanation = payload["explanation"]
    assert explanation["schema_version"] == EXPLANATION_SCHEMA_VERSION
    assert explanation["graph"]["nodes"][0]["id"] == "query"
    assert any(
        item["category"] == "source-boundary predicate pushdown" and item["status"] == "applied"
        for item in explanation["decisions"]
    )
    assert any(item["category"] == "LIMIT termination" for item in explanation["decisions"])


def test_console_overview_has_unicode_and_ascii_structural_modes() -> None:
    payload = explain_user_query_json(
        "SELECT duration FROM @example WHERE title = 'x'",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    unicode_output = render_console_overview(payload, unicode=True, colour=False)
    ascii_output = render_console_overview(payload, unicode=False, colour=False)

    assert "├─" in unicode_output or "└─" in unicode_output
    assert "→" in unicode_output
    assert "├─" not in ascii_output
    assert "→" not in ascii_output
    assert "+-" in ascii_output or "`-" in ascii_output
    assert "->" in ascii_output


def test_console_colour_is_semantic_and_optional() -> None:
    payload = explain_user_query_json(
        "SELECT id FROM @example LIMIT 2",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )

    coloured = render_console_overview(payload, unicode=True, colour=True)
    plain = render_console_overview(payload, unicode=True, colour=False)

    assert "\x1b[" in coloured
    assert "\x1b[" not in plain
    assert "LIMIT termination" in coloured
    assert "LIMIT termination" in plain


def test_auto_console_modes_require_interactive_stream_and_respect_no_color() -> None:
    previous = os.environ.pop("NO_COLOR", None)
    try:
        colour, unicode = resolve_console_modes(
            stream=_Stream(tty=True),
            colour_mode="auto",
            unicode_mode="auto",
        )
        assert colour
        assert unicode

        redirected_colour, redirected_unicode = resolve_console_modes(
            stream=_Stream(tty=False),
            colour_mode="auto",
            unicode_mode="auto",
        )
        assert not redirected_colour
        assert not redirected_unicode

        os.environ["NO_COLOR"] = "1"
        no_colour, still_unicode = resolve_console_modes(
            stream=_Stream(tty=True),
            colour_mode="auto",
            unicode_mode="auto",
        )
        assert not no_colour
        assert still_unicode
    finally:
        if previous is None:
            os.environ.pop("NO_COLOR", None)
        else:
            os.environ["NO_COLOR"] = previous


def test_forced_unicode_rejects_nothing_and_auto_falls_back_for_ascii_encoding() -> None:
    auto_colour, auto_unicode = resolve_console_modes(
        stream=_Stream(tty=True, encoding="ascii"),
        colour_mode="never",
        unicode_mode="auto",
    )
    forced_colour, forced_unicode = resolve_console_modes(
        stream=_Stream(tty=False, encoding="ascii"),
        colour_mode="always",
        unicode_mode="always",
    )

    assert not auto_colour
    assert not auto_unicode
    assert forced_colour
    assert forced_unicode


def test_dot_renderer_is_deterministic_and_contains_semantic_status_styling() -> None:
    payload = explain_user_query_json(
        "SELECT duration FROM @example WHERE title = 'x'",
        source_type="auto",
        tab="all",
        date_format="ymd",
    )
    graph = build_explain_graph(payload)

    first = graph_to_dot(graph)
    second = graph_to_dot(graph)

    assert first == second
    assert first.startswith("digraph yt_discover_explain {\n")
    assert 'shape="diamond"' in first
    assert 'style="dashed"' in first
    assert "complete-metadata" in first


def test_human_explain_includes_plan_overview_without_ansi_when_disabled() -> None:
    output = explain_user_query(
        "SELECT duration FROM @example WHERE title = 'x'",
        source_type="auto",
        tab="all",
        date_format="ymd",
        unicode=True,
        colour=False,
    )

    assert output.startswith("Query plan overview\n")
    assert "Planner decisions" in output
    assert "\x1b[" not in output


def test_cli_json_remains_free_of_ansi_presentation_sequences() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--explain-format",
            "json",
            "--explain",
            "SELECT id FROM @example LIMIT 2",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "\x1b[" not in proc.stdout
    payload = json.loads(proc.stdout)
    assert payload["explanation"]["schema_version"] == EXPLANATION_SCHEMA_VERSION


def test_cli_can_force_ansi_colour_in_captured_console_output() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--colour",
            "always",
            "--unicode",
            "never",
            "--explain",
            "SELECT id FROM @example LIMIT 2",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "\x1b[" in proc.stdout
    assert "├" not in proc.stdout


def test_cli_auto_mode_uses_plain_ascii_when_stdout_is_redirected() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--explain",
            "SELECT id FROM @example LIMIT 2",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert proc.returncode == 0
    assert "\x1b[" not in proc.stdout
    assert "├" not in proc.stdout
    assert "+-- " in proc.stdout or "`-- " in proc.stdout


def test_human_and_json_share_the_same_plan_overview_model() -> None:
    query = "SELECT duration FROM @example WHERE title = 'x' LIMIT 5"
    payload = explain_user_query_json(
        query,
        source_type="auto",
        tab="all",
        date_format="ymd",
    )
    expected = render_console_overview(payload, unicode=True, colour=False)
    human = explain_user_query(
        query,
        source_type="auto",
        tab="all",
        date_format="ymd",
        unicode=True,
        colour=False,
    )

    actual = human.split("\n\nQuery explanation", 1)[0]
    assert actual == expected
