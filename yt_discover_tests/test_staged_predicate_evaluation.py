"""Regression coverage for staged authoritative WHERE evaluation."""

from yt_media_tools.query import parse_query
from yt_media_tools.sources import resolve_source_request
from yt_media_tools.staged_predicates import plan_predicate_stages, rejects_at_enumeration


def _channel():
    return resolve_source_request("https://www.youtube.com/@example", source_type="channel", tab="all")


def test_mixed_and_partitions_exact_enumeration_from_detailed_metadata() -> None:
    query = parse_query("FROM @x WHERE title ILIKE '%linux%' AND duration >= 10m")
    plan = plan_predicate_stages(query, source=_channel())
    assert len(plan.enumeration_terms) == 1
    assert len(plan.residual_terms) == 1
    assert plan.enumeration_fields == frozenset({"title"})
    assert plan.residual_fields == frozenset({"duration"})


def test_mixed_or_remains_residual_as_one_expression() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' OR duration >= 10m")
    plan = plan_predicate_stages(query, source=_channel())
    assert plan.enumeration_terms == ()
    assert len(plan.residual_terms) == 1
    assert plan.residual_fields == frozenset({"title", "duration"})


def test_enumeration_only_or_can_run_as_one_early_term() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' OR id = 'vid00000001'")
    plan = plan_predicate_stages(query, source=_channel())
    assert len(plan.enumeration_terms) == 1
    assert plan.residual_terms == ()
    assert plan.enumeration_fields == frozenset({"id", "title"})


def test_missing_exact_field_is_deferred_not_interpreted_as_null() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' AND duration >= 10m")
    plan = plan_predicate_stages(query, source=_channel())
    assert not rejects_at_enumeration(plan, {"id": "vid00000001"})


def test_acquired_null_enumeration_field_rejects_where_conjunct() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' AND duration >= 10m")
    plan = plan_predicate_stages(query, source=_channel())
    assert rejects_at_enumeration(plan, {"id": "vid00000001", "title": None})


def test_exact_enumeration_failure_rejects_before_detailed_metadata() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' AND duration >= 10m")
    plan = plan_predicate_stages(query, source=_channel())
    assert rejects_at_enumeration(plan, {"id": "vid00000001", "title": "Beta"})
    assert not rejects_at_enumeration(plan, {"id": "vid00000001", "title": "Alpha"})


def test_approximate_upload_date_is_not_promoted_to_authoritative_stage() -> None:
    query = parse_query("FROM @x WHERE title = 'Alpha' AND upload_date >= 2026-04-01")
    plan = plan_predicate_stages(query, source=_channel())
    assert plan.enumeration_fields == frozenset({"title"})
    assert plan.residual_fields == frozenset({"upload_date"})


def test_cli_reduces_detailed_candidates_with_exact_enumeration_term(tmp_path) -> None:
    from yt_discover_tests.test_observability import fake_ytdlp_env, run_cli

    env = fake_ytdlp_env(tmp_path, count=3)
    result = run_cli(
        "-v",
        "--tab",
        "videos",
        "--backend",
        "ytdlp",
        "FROM @example WHERE title = 'Video 1' AND upload_date >= 2026-04-01 AND views >= 1k",
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "1 detailed candidates" in result.stderr
    assert "2 safely rejected before full extraction" in result.stderr
