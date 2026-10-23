"""Capability-driven predicate simplification and branch-elimination proofs."""

from dataclasses import replace

from yt_media_tools.dates import DateContext
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.optimizer_proofs import (
    TRUTH_FALSE,
    TRUTH_TRUE,
    TRUTH_UNKNOWN,
    prove_predicate_truth,
)
from yt_media_tools.planner import plan_query
from yt_media_tools.query import parse_query, resolve_query
from yt_media_tools.schema import QuerySchema
from yt_media_tools.source_capabilities import (
    STRUCTURALLY_UNSUPPORTED,
    FieldCapability,
    selected_facet_capabilities,
)
from yt_media_tools.sources import resolve_source_request


def _source():
    return resolve_source_request("@example", facet="videos")


def _unsupported_duration_facet():
    base = selected_facet_capabilities(_source())
    unsupported = FieldCapability(
        "duration",
        "unavailable",
        "unavailable",
        "unavailable",
        logical_kind="duration",
        structural_support=STRUCTURALLY_UNSUPPORTED,
    )
    return replace(base, field_overrides=base.field_overrides + (unsupported,))


def _patch_capability(monkeypatch):
    import yt_media_tools.optimizer_proofs as proofs

    monkeypatch.setattr(proofs, "selected_facet_capabilities", lambda source: _unsupported_duration_facet())


def _resolved(text: str):
    return resolve_query(parse_query(text), QuerySchema([{"id": "x", "duration": None, "title": "x"}]))


def test_structurally_unavailable_comparison_is_proven_unknown(monkeypatch):
    _patch_capability(monkeypatch)
    query = _resolved("SELECT id FROM @example OF videos WHERE duration >= 1h")
    result = prove_predicate_truth(query.predicate, source=_source())
    assert result.proven
    assert result.truth == TRUTH_UNKNOWN


def test_structurally_unavailable_is_null_is_proven_true(monkeypatch):
    _patch_capability(monkeypatch)
    query = _resolved("SELECT id FROM @example OF videos WHERE duration IS NULL")
    result = prove_predicate_truth(query.predicate, source=_source())
    assert result.proven
    assert result.truth == TRUTH_TRUE


def test_structurally_unavailable_is_not_null_is_proven_false(monkeypatch):
    _patch_capability(monkeypatch)
    query = _resolved("SELECT id FROM @example OF videos WHERE duration IS NOT NULL")
    result = prove_predicate_truth(query.predicate, source=_source())
    assert result.proven
    assert result.truth == TRUTH_FALSE


def test_boolean_three_valued_proof_composition(monkeypatch):
    _patch_capability(monkeypatch)
    query = _resolved("SELECT id FROM @example OF videos WHERE duration >= 1h OR duration IS NULL")
    result = prove_predicate_truth(query.predicate, source=_source())
    assert result.proven
    assert result.truth == TRUTH_TRUE


def test_optimizer_replaces_proven_predicate_with_sql_constant(monkeypatch):
    _patch_capability(monkeypatch)
    query = _resolved("SELECT id FROM @example OF videos WHERE duration >= 1h")
    result = optimise_query(query, source=_source())
    assert result.query.predicate.value is None
    decision = next(item for item in result.decisions if item.rule == "capability-constant-predicate")
    assert decision.proofs and all(proof.proven for proof in decision.proofs)


def test_planner_skips_branch_when_where_cannot_be_true(monkeypatch):
    _patch_capability(monkeypatch)
    query = parse_query("SELECT id FROM @example OF videos WHERE duration >= 1h")
    plan = plan_query(query, source=_source(), dates=DateContext())
    assert plan.source_branch_eliminated
    assert plan.acquisition.mode == "skip"
    assert plan.physical_request.mode == "skip"
    assert plan.cost_class == "none"
    assert plan.elimination_proof is not None and plan.elimination_proof.proven


def test_planner_does_not_skip_structurally_true_null_test(monkeypatch):
    _patch_capability(monkeypatch)
    query = parse_query("SELECT id FROM @example OF videos WHERE duration IS NULL")
    plan = plan_query(query, source=_source(), dates=DateContext())
    assert not plan.source_branch_eliminated
    assert plan.acquisition.mode != "skip"
