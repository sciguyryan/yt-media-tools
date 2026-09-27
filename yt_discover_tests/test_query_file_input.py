"""Tests for loading reusable yt-sql queries from UTF-8 files."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt_media_tools.discover_cli import build_parser, parse_user_query
from yt_media_tools.query import format_query


def _parse_args(*arguments: str):
    return build_parser().parse_args(list(arguments))


def test_query_file_is_parsed_as_path() -> None:
    args = _parse_args("--query-file", "queries/recent.yt-sql")
    assert args.query_file == Path("queries/recent.yt-sql")


def test_query_file_uses_the_same_query_path_as_inline_query(tmp_path: Path) -> None:
    text = "SELECT id, title FROM @example WHERE duration < :maximum ORDER BY title ASC\n"
    query_file = tmp_path / "reusable.yt-sql"
    query_file.write_text(text, encoding="utf-8")

    file_query = parse_user_query(_parse_args("--param", "maximum=1h", "--query-file", str(query_file)))
    inline_query = parse_user_query(_parse_args("--param", "maximum=1h", "--query", text))

    assert file_query == inline_query
    assert format_query(file_query) == format_query(inline_query)


def test_query_file_can_be_combined_with_a_positional_source(tmp_path: Path) -> None:
    query_file = tmp_path / "predicate.yt-sql"
    query_file.write_text("WHERE duration < 1h ORDER BY upload_date DESC", encoding="utf-8")

    query = parse_user_query(_parse_args("@example", "--query-file", str(query_file)))

    assert query.predicate is not None
    assert query.order_by
    assert query.from_source is None


def test_query_file_conflicts_with_other_explicit_query_inputs(tmp_path: Path) -> None:
    query_file = tmp_path / "query.yt-sql"
    query_file.write_text("FROM @example", encoding="utf-8")
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--query-file", str(query_file), "--query", "FROM @other"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--query-file", str(query_file), "--where", "duration < 1h"])


def test_positional_complete_query_conflicts_with_query_file(tmp_path: Path) -> None:
    query_file = tmp_path / "query.yt-sql"
    query_file.write_text("FROM @example", encoding="utf-8")
    args = _parse_args("FROM @other", "--query-file", str(query_file))

    with pytest.raises(ValueError, match="positional complete query.*--query-file"):
        parse_user_query(args, "FROM @other")


def test_missing_query_file_reports_a_deterministic_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.yt-sql"

    with pytest.raises(ValueError, match=r"^cannot read query file .*missing\.yt-sql:"):
        parse_user_query(_parse_args("--query-file", str(missing)))


def test_query_file_requires_utf8(tmp_path: Path) -> None:
    query_file = tmp_path / "invalid.yt-sql"
    query_file.write_bytes(b"FROM @example\xff")

    with pytest.raises(ValueError, match=r"expected UTF-8 text$"):
        parse_user_query(_parse_args("--query-file", str(query_file)))
