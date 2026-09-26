"""Compound acquisition must preserve independent source-boundary planning."""

from __future__ import annotations

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_source_boundaries
from yt_media_tools.query_parser import parse_query
from yt_media_tools.sources import resolve_source_request


def _plans(source: str):
    query = parse_query(source)
    requests = (("@example", "videos"), ("@example", "live"))
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    return plan_source_boundaries(query, requests=requests, sources=sources, dates=DateContext())


def test_multi_facet_union_retains_independent_physical_plans() -> None:
    plans = _plans(
        "SELECT id, title FROM @example OF videos, live WHERE title ILIKE '%welcome%' ORDER BY upload_date ASC"
    )
    assert [(plan.source_name, plan.facet) for plan in plans] == [
        ("@example", "videos"),
        ("@example", "live"),
    ]
    assert all(plan.physical_acquisition is not None for plan in plans)
    assert all(plan.metadata_requirements is not None for plan in plans)


def test_explicit_union_uses_the_same_source_boundary_contract() -> None:
    shorthand = _plans("SELECT id FROM @example OF videos, live")
    explicit = _plans("SELECT id FROM @example OF videos UNION ALL SELECT id FROM @example OF live")
    assert [(plan.facet, plan.required_fields, plan.metadata_depth, plan.acquisition.mode) for plan in shorthand] == [
        (plan.facet, plan.required_fields, plan.metadata_depth, plan.acquisition.mode) for plan in explicit
    ]


def test_compound_order_fields_are_acquired_by_every_contributing_boundary() -> None:
    plans = _plans(
        "SELECT CONCAT(id, ' # ', title) FROM @example OF videos, live "
        "WHERE title ILIKE '%welcome%' "
        "ORDER BY upload_date ASC, release_timestamp ASC"
    )
    for plan in plans:
        assert {"upload_date", "release_timestamp"} <= plan.required_fields
        assert {"upload_date", "release_timestamp"} <= plan.metadata_requirements.detailed_fields
