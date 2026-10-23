"""Regression checks for the initial Python portable candidate execution boundary."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "yt-sql" / "run_python_candidate.py"
CASE = ROOT / "yt-sql" / "cases" / "smoke" / "source_order_limit"


def _adapter():
    import sys

    sys.path.insert(0, str(ROOT / "yt-sql"))
    spec = importlib.util.spec_from_file_location("portable_python_candidate_adapter", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_case_observed_against_existing_expected() -> None:
    observed = _adapter().observe(CASE)
    assert observed == json.loads((CASE / "expected.json").read_text(encoding="utf-8"))


def test_undeclared_configuration_is_rejected() -> None:
    adapter = _adapter()
    with pytest.raises(adapter.AdapterError, match="undeclared"):
        adapter.observe(CASE, configuration="unoptimised")


def test_portable_value_encodings() -> None:
    adapter = _adapter()
    assert adapter._portable(42) == {"type": "integer", "value": "42"}
    assert adapter._portable(True) is True
    with pytest.raises(adapter.AdapterError, match="unsupported"):
        adapter._portable(1.25)


def test_lexical_failure_is_portable_syntax(tmp_path: Path) -> None:
    adapter = _adapter()
    # Use a copy of the accepted case under a temporary corpus root.
    import shutil

    root = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", root / "datasets")
    destination = root / "cases" / "smoke" / "source_order_limit"
    shutil.copytree(CASE, destination)
    (destination / "query.sql").write_text("SELECT id FROM @yt_sql_fixture WHERE !", encoding="utf-8")
    assert adapter.observe(destination, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "syntax"},
    }


def _topology_case(tmp_path: Path, dataset: str, query: str) -> tuple[Path, Path]:
    import shutil

    root = tmp_path / "yt-sql"
    shutil.copytree(ROOT / "yt-sql" / "datasets", root / "datasets")
    case = root / "cases" / "smoke" / "source_order_limit"
    shutil.copytree(CASE, case)
    manifest = json.loads((case / "test.json").read_text(encoding="utf-8"))
    manifest["datasets"] = [dataset]
    (case / "test.json").write_text(json.dumps(manifest), encoding="utf-8")
    (case / "query.sql").write_text(query, encoding="utf-8")
    return root, case


def test_source_topology_single_source(tmp_path: Path) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel ORDER BY id")
    result = _adapter().observe(case, root=root)
    assert result["rows"] == [["yt-channel-1"], ["yt-channel-2"]]


def test_source_topology_rejects_unbound_handle(tmp_path: Path) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @missing")
    adapter = _adapter()
    with pytest.raises(adapter.AdapterError, match="not bound"):
        adapter.observe(case, root=root)


def test_facet_topology_empty_membership(tmp_path: Path) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-facets-v1", "SELECT id FROM @youtube_channel OF shorts")
    result = _adapter().observe(case, root=root)
    assert result["rows"] == []


@pytest.mark.parametrize(
    ("query", "expected_rows"),
    [
        (
            (
                "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_playlist AS a "
                "INNER JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"
            ),
            [["shared-id", "shared-id"]],
        ),
        (
            ("WITH selected AS (SELECT id FROM @youtube_channel) SELECT id FROM selected ORDER BY id"),
            [["yt-channel-1"], ["yt-channel-2"]],
        ),
        (
            ("SELECT id FROM @youtube_playlist UNION ALL SELECT id FROM @twitch_archive"),
            [["yt-playlist-1"], ["shared-id"], ["twitch-1"], ["shared-id"]],
        ),
    ],
    ids=["inner-join", "cte", "union-all"],
)
def test_relational_source_topology_execution(
    tmp_path: Path,
    query: str,
    expected_rows: list[list[str]],
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    observed = _adapter().observe(case, root=root)
    assert observed["outcome"] == "rows"
    assert observed["rows"] == expected_rows


def test_relational_optimisation_equivalence(tmp_path: Path) -> None:
    query = (
        "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_playlist AS a "
        "INNER JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"
    )
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    manifest_path = case / "test.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution"] = {
        "configurations": [
            {"id": "optimised", "settings": {"optimisation": "enabled"}},
            {"id": "unoptimised", "settings": {"optimisation": "disabled"}},
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    adapter = _adapter()
    assert adapter.observe(case, root=root, configuration="optimised") == adapter.observe(
        case, root=root, configuration="unoptimised"
    )


@pytest.mark.parametrize(
    ("query", "expected_rows"),
    [
        (
            (
                "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_playlist AS a "
                "LEFT JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"
            ),
            [["shared-id", "shared-id"], ["yt-playlist-1", None]],
        ),
        (
            ("SELECT a.id FROM @youtube_playlist AS a SEMI JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"),
            [["shared-id"]],
        ),
        (
            ("SELECT a.id FROM @youtube_playlist AS a ANTI JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"),
            [["yt-playlist-1"]],
        ),
        (
            (
                "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_playlist AS a "
                "INNER JOIN @twitch_archive AS b ON a.view_count = b.view_count"
            ),
            [],
        ),
    ],
    ids=["left-unmatched", "semi-match", "anti-unmatched", "null-join-predicate"],
)
def test_relational_join_boundaries(
    tmp_path: Path,
    query: str,
    expected_rows: list[list[str | None]],
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    observed = _adapter().observe(case, root=root)
    assert observed["outcome"] == "rows"
    assert observed["rows"] == expected_rows


def test_empty_facet_join_does_not_acquire_parent_records(tmp_path: Path) -> None:
    query = (
        "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_channel AS a "
        "LEFT JOIN @youtube_channel OF shorts AS b ON a.id = b.id ORDER BY a.id"
    )
    root, case = _topology_case(tmp_path, "heterogeneous-facets-v1", query)
    observed = _adapter().observe(case, root=root)
    assert observed["rows"] == [["yt-channel-1", None], ["yt-channel-2", None]]


@pytest.mark.parametrize(
    "query",
    [
        (
            "SELECT a.id AS left_id, b.id AS right_id FROM @youtube_playlist AS a "
            "LEFT JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"
        ),
        ("SELECT a.id FROM @youtube_playlist AS a SEMI JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"),
        ("SELECT a.id FROM @youtube_playlist AS a ANTI JOIN @twitch_archive AS b ON a.id = b.id ORDER BY a.id"),
    ],
    ids=["left", "semi", "anti"],
)
def test_join_family_optimisation_equivalence(tmp_path: Path, query: str) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    manifest_path = case / "test.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution"] = {
        "configurations": [
            {"id": "optimised", "settings": {"optimisation": "enabled"}},
            {"id": "unoptimised", "settings": {"optimisation": "disabled"}},
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    adapter = _adapter()
    assert adapter.observe(case, root=root, configuration="optimised") == adapter.observe(
        case, root=root, configuration="unoptimised"
    )


@pytest.mark.parametrize(
    ("query", "expected_rows"),
    [
        (
            (
                "WITH matched AS (SELECT a.id AS id FROM @youtube_playlist AS a "
                "INNER JOIN @twitch_archive AS b ON a.id = b.id) "
                "SELECT id FROM matched ORDER BY id"
            ),
            [["shared-id"]],
        ),
        (
            (
                "SELECT a.id AS id FROM @youtube_playlist AS a "
                "SEMI JOIN @twitch_archive AS b ON a.id = b.id "
                "UNION ALL SELECT id FROM @twitch_archive"
            ),
            [["shared-id"], ["twitch-1"], ["shared-id"]],
        ),
    ],
    ids=["join-inside-cte", "semi-join-union-all"],
)
def test_composed_relational_source_execution(
    tmp_path: Path,
    query: str,
    expected_rows: list[list[str]],
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    observed = _adapter().observe(case, root=root)
    assert observed["outcome"] == "rows"
    assert observed["rows"] == expected_rows


@pytest.mark.parametrize(
    ("query", "expected_rows"),
    [
        (
            (
                "SELECT a.id AS channel_id, b.id AS playlist_id "
                "FROM @youtube_channel OF videos AS a "
                "INNER JOIN @youtube_playlist OF videos AS b ON a.view_count = b.view_count "
                "ORDER BY a.id"
            ),
            [["yt-channel-2", "yt-playlist-1"]],
        ),
        (
            ("SELECT id FROM @youtube_channel OF shorts UNION ALL SELECT id FROM @twitch_archive OF streams"),
            [["twitch-1"], ["shared-id"]],
        ),
    ],
    ids=["join-between-facets", "empty-facet-union"],
)
def test_composed_facet_execution(
    tmp_path: Path,
    query: str,
    expected_rows: list[list[str]],
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-facets-v1", query)
    observed = _adapter().observe(case, root=root)
    assert observed["outcome"] == "rows"
    assert observed["rows"] == expected_rows


@pytest.mark.parametrize(
    ("dataset", "query"),
    [
        (
            "heterogeneous-sources-v1",
            (
                "WITH matched AS (SELECT a.id AS id FROM @youtube_playlist AS a "
                "INNER JOIN @twitch_archive AS b ON a.id = b.id) "
                "SELECT id FROM matched ORDER BY id"
            ),
        ),
        (
            "heterogeneous-sources-v1",
            (
                "SELECT a.id AS id FROM @youtube_playlist AS a "
                "SEMI JOIN @twitch_archive AS b ON a.id = b.id "
                "UNION ALL SELECT id FROM @twitch_archive"
            ),
        ),
        (
            "heterogeneous-facets-v1",
            (
                "SELECT a.id AS channel_id, b.id AS playlist_id "
                "FROM @youtube_channel OF videos AS a "
                "INNER JOIN @youtube_playlist OF videos AS b ON a.view_count = b.view_count "
                "ORDER BY a.id"
            ),
        ),
        (
            "heterogeneous-facets-v1",
            ("SELECT id FROM @youtube_channel OF shorts UNION ALL SELECT id FROM @twitch_archive OF streams"),
        ),
    ],
    ids=["cte-join", "semi-join-union", "facet-join", "empty-facet-union"],
)
def test_composed_relations_preserve_optimiser_equivalence(
    tmp_path: Path,
    dataset: str,
    query: str,
) -> None:
    root, case = _topology_case(tmp_path, dataset, query)
    manifest_path = case / "test.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["execution"] = {
        "configurations": [
            {"id": "optimised", "settings": {"optimisation": "enabled"}},
            {"id": "unoptimised", "settings": {"optimisation": "disabled"}},
        ]
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    adapter = _adapter()
    assert adapter.observe(case, root=root, configuration="optimised") == adapter.observe(
        case, root=root, configuration="unoptimised"
    )


def test_grammatical_failure_is_portable_syntax(tmp_path: Path) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel WHERE")
    assert _adapter().observe(case, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "syntax"},
    }


def test_semantic_parser_failure_is_not_portable_syntax(tmp_path: Path) -> None:
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        "SELECT id FROM @youtube_channel WHERE duraton < 1h",
    )
    adapter = _adapter()
    assert adapter.observe(case, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "resolution"},
    }


def test_adapter_does_not_convert_unexpected_resolver_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel")
    from yt_media_tools import query

    def broken_resolver(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected resolver failure")

    monkeypatch.setattr(query, "resolve_query", broken_resolver)
    with pytest.raises(RuntimeError, match="unexpected resolver failure"):
        _adapter().observe(case, root=root)


def test_unknown_relation_field_is_portable_resolution(tmp_path: Path) -> None:
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        "SELECT a.nonexistent FROM @youtube_channel AS a",
    )
    assert _adapter().observe(case, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "resolution"},
    }


def test_unclassified_semantic_diagnostic_is_not_portable(tmp_path: Path) -> None:
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        "SELECT a.id AS id, b.id AS id FROM @youtube_channel AS a INNER JOIN @youtube_playlist AS b ON a.id = b.id",
    )
    adapter = _adapter()
    with pytest.raises((adapter.AdapterError, ValueError)):
        adapter.observe(case, root=root)


@pytest.mark.parametrize(
    "query",
    [
        ("SELECT missing.id FROM @youtube_channel AS a INNER JOIN @youtube_playlist AS b ON a.id = b.id"),
        ("SELECT id FROM @youtube_channel AS a INNER JOIN @youtube_playlist AS b ON a.id = b.id"),
        ("SELECT missing.* FROM @youtube_channel AS a INNER JOIN @youtube_playlist AS b ON a.id = b.id"),
    ],
    ids=["unknown-qualifier", "ambiguous-unqualified-field", "unknown-wildcard-qualifier"],
)
def test_reviewed_join_resolution_diagnostics(tmp_path: Path, query: str) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", query)
    assert _adapter().observe(case, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "resolution"},
    }


@pytest.mark.parametrize("function", ["AVG", "SUM"])
def test_non_numeric_aggregate_is_portable_type(tmp_path: Path, function: str) -> None:
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        f"SELECT {function}(title) AS value FROM @youtube_channel",
    )
    assert _adapter().observe(case, root=root) == {
        "version": 1,
        "outcome": "error",
        "error": {"category": "type"},
    }


def test_unexpected_evaluator_failure_is_not_portable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel")
    from yt_media_tools import query

    def broken_evaluator(*args: object, **kwargs: object) -> None:
        raise RuntimeError("unexpected evaluator failure")

    monkeypatch.setattr(query, "apply_query", broken_evaluator)
    with pytest.raises(RuntimeError, match="unexpected evaluator failure"):
        _adapter().observe(case, root=root)


def test_unreviewed_semantic_reason_does_not_become_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel")
    from yt_media_tools import query
    from yt_media_tools.query_model import QuerySemanticError

    def unreviewed_resolver(*args: object, **kwargs: object) -> None:
        raise QuerySemanticError("SELECT id", "unreviewed semantic failure", 0)

    monkeypatch.setattr(query, "resolve_query", unreviewed_resolver)
    adapter = _adapter()
    with pytest.raises(adapter.AdapterError, match="unclassified Python language diagnostic"):
        adapter.observe(case, root=root)


@pytest.mark.parametrize("failure", [TypeError, ValueError, ZeroDivisionError])
def test_evaluator_builtin_failures_are_not_portable_diagnostics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: type[Exception],
) -> None:
    """Runtime exceptions are not evidence of a reviewed YT-SQL evaluation error."""
    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel")
    from yt_media_tools import query

    def failing_evaluator(*args: object, **kwargs: object) -> None:
        raise failure("unreviewed evaluator failure")

    monkeypatch.setattr(query, "apply_query", failing_evaluator)
    with pytest.raises(failure, match="unreviewed evaluator failure"):
        _adapter().observe(case, root=root)


def test_explicit_clock_reaches_python_date_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime

    from yt_media_tools import dates

    root, case = _topology_case(tmp_path, "heterogeneous-sources-v1", "SELECT id FROM @youtube_channel ORDER BY id")
    manifest = json.loads((case / "test.json").read_text(encoding="utf-8"))
    manifest["execution"] = {
        "configurations": [
            {"id": "offset", "settings": {"clock": "2026-09-01T12:30:00+02:00"}},
        ]
    }
    (case / "test.json").write_text(json.dumps(manifest), encoding="utf-8")
    captured: list[datetime] = []
    original = dates.DateContext

    def capture_context(*, now: datetime) -> dates.DateContext:
        captured.append(now)
        return original(now=now)

    monkeypatch.setattr(dates, "DateContext", capture_context)
    result = _adapter().observe(case, configuration="offset", root=root)
    assert result["outcome"] == "rows"
    assert captured == [datetime.fromisoformat("2026-09-01T12:30:00+02:00")]


def test_portable_parameter_binding_preserves_scalar_types_and_case() -> None:
    adapter = _adapter()
    bind = adapter._bind_portable_parameters
    assert (
        bind(
            "SELECT :N, :n, :flag, :nothing",
            {
                "N": {"type": "integer", "value": "12"},
                "n": {"type": "decimal", "value": "1.50"},
                "flag": True,
                "nothing": None,
            },
        )
        == "SELECT 12, 1.50, TRUE, NULL"
    )
    assert bind("SELECT ':name', :name", {"name": "O'Brien"}) == "SELECT ':name', 'O''Brien'"


def test_portable_parameter_binding_rejects_missing_and_unused() -> None:
    adapter = _adapter()
    bind = adapter._bind_portable_parameters
    with pytest.raises(adapter.AdapterError, match="missing"):
        bind("SELECT :missing", {})
    with pytest.raises(adapter.AdapterError, match="unused"):
        bind("SELECT 1", {"unused": "x"})


def test_portable_parameter_binding_executes_query(tmp_path: Path) -> None:
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        "SELECT id FROM @youtube_channel WHERE id = :selected ORDER BY id",
    )
    manifest = json.loads((case / "test.json").read_text(encoding="utf-8"))
    manifest["parameters"] = {"selected": "yt-channel-2"}
    (case / "test.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _adapter().observe(case, root=root)["rows"] == [["yt-channel-2"]]


def test_portable_timestamp_parameter_uses_native_datetime_literal() -> None:
    adapter = _adapter()
    bind = adapter._bind_portable_parameters
    from yt_media_tools.query import parse_query

    values = {
        "instant": {"type": "timestamp", "value": "2026-09-01T12:30:00+02:00"},
        "fraction": {"type": "timestamp", "value": "2026-09-01T12:30:00.123456+02:00"},
    }
    assert bind("SELECT :instant, :fraction", values) == (
        "SELECT 2026-09-01T10:30:00.000000Z, 2026-09-01T10:30:00.123456Z"
    )
    parse_query(
        "SELECT id FROM @youtube_channel WHERE release_timestamp >= :instant".replace(
            ":instant", bind(":instant", {"instant": values["instant"]})
        )
    )


def test_portable_timestamp_binding_preserves_quoted_placeholder() -> None:
    adapter = _adapter()
    assert (
        adapter._bind_portable_parameters(
            "SELECT ':instant', :instant",
            {"instant": {"type": "timestamp", "value": "2026-09-01T00:00:00Z"}},
        )
        == "SELECT ':instant', 2026-09-01T00:00:00.000000Z"
    )


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026-09-01T19:00:00+02:00", [["yt-channel-1"]]),
        ("2026-09-01T16:00:00Z", []),
        ("2026-09-02T17:00:00Z", [["yt-channel-1"], ["yt-channel-2"]]),
    ],
)
def test_timestamp_parameter_filters_portable_source_records(
    tmp_path: Path,
    timestamp: str,
    expected: list[list[str]],
) -> None:
    """Compare instants through the parser, resolver and evaluator, not just the binder."""
    root, case = _topology_case(
        tmp_path,
        "heterogeneous-sources-v1",
        "SELECT id FROM @youtube_channel WHERE release_timestamp < :cutoff ORDER BY id",
    )
    manifest = json.loads((case / "test.json").read_text(encoding="utf-8"))
    manifest["parameters"] = {"cutoff": {"type": "timestamp", "value": timestamp}}
    (case / "test.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _adapter().observe(case, root=root)["rows"] == expected
