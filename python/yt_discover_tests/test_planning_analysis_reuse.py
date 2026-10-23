"""Focused coverage for reuse of semantic analysis during physical planning."""

from datetime import datetime

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import (
    AcquisitionPlan,
    assess_cost,
    plan_limit_termination,
    plan_metadata_requirements,
    plan_query,
)
from yt_media_tools.query import parse_query
from yt_media_tools.query_properties import analyse_query
from yt_media_tools.query_resolver import resolve_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_model import SourceSpec


def _source() -> SourceSpec:
    return SourceSpec("example", "channel", "https://www.youtube.com/@example", "videos")


def _resolved_query():
    return resolve_query(
        parse_query("SELECT id, title FROM @example OF videos WHERE duration < 10m LIMIT 3"),
        QuerySchema(()),
    )


def test_planning_helpers_accept_precomputed_query_properties() -> None:
    query = _resolved_query()
    source = _source()
    properties = analyse_query(query, source=source)

    assert plan_metadata_requirements(query, source=source, properties=properties) == plan_metadata_requirements(
        query, source=source
    )
    assert plan_limit_termination(query, source=source, properties=properties) == plan_limit_termination(
        query, source=source
    )
    assert assess_cost(query, AcquisitionPlan("full", "test"), source=source, properties=properties) == assess_cost(
        query, AcquisitionPlan("full", "test"), source=source
    )


def test_plan_query_reuses_top_level_query_properties(monkeypatch) -> None:
    query = _resolved_query()
    source = _source()

    import yt_media_tools.planner as planner

    original = planner.analyse_query
    top_level_calls = 0

    def counted(candidate, *, source=None):
        nonlocal top_level_calls
        if candidate is query:
            top_level_calls += 1
        return original(candidate, source=source)

    monkeypatch.setattr(planner, "analyse_query", counted)
    plan = plan_query(query, source=source, dates=DateContext(now=datetime(2026, 9, 15)))

    assert plan.properties.required_fields
    assert top_level_calls == 1
