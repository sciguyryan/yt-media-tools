import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, filename):
    module_name = filename.removesuffix(".py")
    return importlib.import_module(f"yt_media_tools.{module_name}")


def test_null_comparison_requires_explicit_is_null():
    query = load_module("yt_query_test_null", "query.py")
    row = {"duration": None}
    assert not query.evaluate_expression(row, query.parse_expression("duration != 10"))
    assert query.evaluate_expression(row, query.parse_expression("duration IS NULL"))


def test_parameterised_contains():
    query = load_module("yt_query_test_contains", "query.py")
    row = {"title": "Alpha Beta"}
    assert query.evaluate_expression(
        row,
        query.parse_expression("title CONTAINS :needle"),
        {"needle": "beta"},
    )


def test_distinct_limit_does_not_allow_early_source_stop():
    planner = load_module("yt_planner_test_distinct", "planner.py")
    assert (
        planner.acquisition_limit(
            {"limit": 10, "offset": 0, "order": None, "distinct": True},
            None,
            "yt-dlp",
        )
        is None
    )


def test_plain_limit_and_offset_can_bound_yt_dlp():
    planner = load_module("yt_planner_test_limit", "planner.py")
    assert (
        planner.acquisition_limit(
            {"limit": 10, "offset": 3, "order": None, "distinct": False},
            None,
            "yt-dlp",
        )
        == 13
    )


def test_parsed_query_date_is_timezone_aware():
    query = load_module("yt_query_test_timezone", "query.py")
    value = query.coerce_value("date", "2026-09-07")

    assert getattr(value, "tzinfo", None) is not None
    assert value.utcoffset().total_seconds() == 0
