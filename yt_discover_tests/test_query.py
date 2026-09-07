import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def test_null_comparison_requires_explicit_is_null():
    query = load_module("yt_query_test_null", "yt_query.py")
    row = {"duration": None}
    assert not query.evaluate_expression(row, query.parse_expression("duration != 10"))
    assert query.evaluate_expression(row, query.parse_expression("duration IS NULL"))

def test_parameterised_contains():
    query = load_module("yt_query_test_contains", "yt_query.py")
    row = {"title": "Alpha Beta"}
    assert query.evaluate_expression(
        row,
        query.parse_expression("title CONTAINS :needle"),
        {"needle": "beta"},
    )

def test_distinct_limit_does_not_allow_early_source_stop():
    planner = load_module("yt_planner_test_distinct", "yt_planner.py")
    assert planner.acquisition_limit(
        {"limit": 10, "offset": 0, "order": None, "distinct": True},
        None,
        "yt-dlp",
    ) is None

def test_plain_limit_and_offset_can_bound_yt_dlp():
    planner = load_module("yt_planner_test_limit", "yt_planner.py")
    assert planner.acquisition_limit(
        {"limit": 10, "offset": 3, "order": None, "distinct": False},
        None,
        "yt-dlp",
    ) == 13
