"""Coverage for authoritative field-depth planning and metadata pruning."""

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import AcquisitionPlan, assess_cost, plan_metadata_requirements, plan_query
from yt_media_tools.query import parse_query
from yt_media_tools.sources import resolve_source_request


def _channel():
    return resolve_source_request("https://www.youtube.com/@example", source_type="channel", tab="all")


def test_exact_flat_fields_need_no_detailed_metadata() -> None:
    query = parse_query("SELECT id, title FROM @x WHERE title ILIKE '%linux%' ORDER BY title")
    requirements = plan_metadata_requirements(query, source=_channel())

    assert requirements.enumeration_fields == frozenset({"id", "title"})
    assert requirements.detailed_fields == frozenset()
    assert requirements.predicate_enumeration_fields == frozenset({"title"})
    assert requirements.predicate_detailed_fields == frozenset()
    assert not requirements.requires_detailed_metadata


def test_approximate_flat_values_remain_detailed_requirements() -> None:
    query = parse_query("SELECT title, view_count FROM @x WHERE view_count >= 10")
    requirements = plan_metadata_requirements(query, source=_channel())

    assert requirements.enumeration_fields == frozenset({"title"})
    assert requirements.detailed_fields == frozenset({"view_count"})
    assert requirements.predicate_enumeration_fields == frozenset()
    assert requirements.predicate_detailed_fields == frozenset({"view_count"})
    assert requirements.requires_detailed_metadata


def test_dynamic_fields_are_never_assumed_available_from_enumeration() -> None:
    query = parse_query("SELECT id, description FROM @x WHERE title = 'Alpha'")
    requirements = plan_metadata_requirements(query, source=_channel())

    assert requirements.enumeration_fields == frozenset({"id", "title"})
    assert requirements.detailed_fields == frozenset({"description"})
    assert requirements.predicate_enumeration_fields == frozenset({"title"})


def test_physical_request_exposes_stage_partition() -> None:
    query = parse_query("SELECT title, duration FROM @x WHERE title LIKE 'A%' LIMIT 5")
    plan = plan_query(query, source=_channel(), dates=DateContext())

    assert plan.physical_request.required_fields == frozenset({"title", "duration"})
    assert plan.physical_request.enumeration_fields == frozenset({"title"})
    assert plan.physical_request.detailed_fields == frozenset({"duration"})
    assert plan.metadata_requirements == plan_metadata_requirements(query, source=_channel())


def test_full_lightweight_enumeration_is_not_classified_as_detailed_acquisition() -> None:
    query = parse_query("SELECT title FROM @x ORDER BY title")
    cost_class, reason = assess_cost(query, AcquisitionPlan("full", "test"), source=_channel())

    assert cost_class == "high"
    assert "lightweight metadata" in reason
