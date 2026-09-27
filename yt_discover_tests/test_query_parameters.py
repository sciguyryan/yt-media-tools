"""Named yt-sql parameter binding and validation at the CLI boundary."""

from __future__ import annotations

from yt_discover_tests.cli_harness import run_cli


def test_parameter_binding_check_query() -> None:
    proc = run_cli(
        "--param",
        "start=2026-08-01",
        "--check-query",
        "SELECT id FROM @x WHERE upload_date >= :start",
    )
    assert proc.returncode == 0, proc.stderr
    assert "upload_date >= '2026-08-01'" in proc.stdout


def test_missing_parameter_is_an_error() -> None:
    proc = run_cli("--check-query", "SELECT id FROM @x WHERE title = :name")
    assert proc.returncode != 0
    assert "missing value for query parameter" in proc.stderr


def test_parameters_do_not_expand_inside_quoted_strings() -> None:
    proc = run_cli(
        "--param",
        "name=unused",
        "--check-query",
        "SELECT id FROM @x WHERE title = ':name'",
    )
    assert proc.returncode != 0
    assert "unused query parameter" in proc.stderr


def test_parameter_names_are_case_insensitive() -> None:
    proc = run_cli(
        "--param",
        "Needle=Alpha",
        "--check-query",
        "SELECT id FROM @x WHERE title = :needle",
    )
    assert proc.returncode == 0, proc.stderr
    assert "title = 'Alpha'" in proc.stdout


def test_parameter_values_escape_single_quotes() -> None:
    proc = run_cli(
        "--param",
        "needle=O'Brien",
        "--check-query",
        "SELECT id FROM @x WHERE title = :needle",
    )
    assert proc.returncode == 0, proc.stderr
    assert "O''Brien" in proc.stdout


def test_duplicate_parameter_names_are_rejected_case_insensitively() -> None:
    proc = run_cli(
        "--param",
        "name=first",
        "--param",
        "NAME=second",
        "--check-query",
        "SELECT id FROM @x WHERE title = :name",
    )
    assert proc.returncode != 0
    assert "duplicate query parameter" in proc.stderr


def test_invalid_parameter_name_is_rejected() -> None:
    proc = run_cli(
        "--param",
        "9name=value",
        "--check-query",
        "SELECT id FROM @x WHERE title = :name",
    )
    assert proc.returncode != 0
    assert "invalid parameter name" in proc.stderr


def test_parameter_requires_name_value_separator() -> None:
    proc = run_cli(
        "--param",
        "name",
        "--check-query",
        "SELECT id FROM @x WHERE title = :name",
    )
    assert proc.returncode != 0
    assert "--param requires NAME=VALUE" in proc.stderr


def test_parameter_binding_composes_with_collection_index_predicate() -> None:
    proc = run_cli(
        "--param",
        "needle=alpha",
        "--check-query",
        "SELECT id FROM @x WHERE tags[0] = :needle",
    )
    assert proc.returncode == 0, proc.stderr
    assert "tags[0] = 'alpha'" in proc.stdout
