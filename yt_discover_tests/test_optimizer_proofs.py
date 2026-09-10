"""Proof-framework coverage for conservative optimiser decisions."""

from yt_media_tools.optimizer import optimise_query
from yt_media_tools.optimizer_proofs import (
    NOT_PROVEN,
    PROVEN,
    compose_proofs,
    prove_expression_constant,
    prove_expression_deterministic,
    prove_field_structurally_unavailable,
    prove_query_independent_of_fields,
)
from yt_media_tools.query import parse_query, resolve_query
from yt_media_tools.query_model import Field, ScalarFunction
from yt_media_tools.schema import QuerySchema
from yt_media_tools.sources import SourceSpec


def _resolved(text: str):
    rows = [{"id": "a", "title": "Example", "duration": 20, "view_count": 5}]
    return resolve_query(parse_query(text), QuerySchema(rows))


def test_literal_expression_is_proven_constant_and_deterministic():
    expression = _resolved("SELECT 1 + 2 FROM @x").select[0].expression
    assert prove_expression_constant(expression).status == PROVEN
    assert prove_expression_deterministic(expression).status == PROVEN


def test_unseeded_random_refuses_determinism_and_constantness():
    expression = ScalarFunction("RANDOM", (), kind="number")
    assert prove_expression_deterministic(expression).status == NOT_PROVEN
    assert prove_expression_constant(expression).status == NOT_PROVEN


def test_seeded_random_is_deterministic_but_not_constant():
    expression = _resolved("SELECT RANDOM(42) FROM @x").select[0].expression
    assert prove_expression_deterministic(expression).status == PROVEN
    assert prove_expression_constant(expression).status == NOT_PROVEN


def test_missing_source_contract_cannot_prove_structural_unavailability():
    proof = prove_field_structurally_unavailable(Field("duration"), source=None)
    assert proof.status == NOT_PROVEN


def test_unknown_dynamic_field_is_not_assumed_structurally_unavailable():
    source = SourceSpec("generic", "test:thing", "test:thing", "thing", None)
    proof = prove_field_structurally_unavailable("future_field", source=source)
    assert proof.status == NOT_PROVEN


def test_query_field_independence_uses_semantic_requirements():
    query = _resolved("SELECT title FROM @x WHERE duration > 10s")
    assert prove_query_independent_of_fields(query, {"view_count"}).status == PROVEN
    assert prove_query_independent_of_fields(query, {"duration"}).status == NOT_PROVEN


def test_proof_composition_refuses_when_any_prerequisite_is_unproven():
    deterministic = prove_expression_deterministic(_resolved("SELECT 1 FROM @x").select[0].expression)
    volatile = prove_expression_deterministic(ScalarFunction("RANDOM", (), kind="number"))
    proof = compose_proofs("safe-rewrite", deterministic, volatile)
    assert proof.status == NOT_PROVEN


def test_duplicate_predicate_decision_retains_determinism_proof():
    query = _resolved("SELECT id FROM @x WHERE duration > 10s AND duration > 10s")
    result = optimise_query(query)
    decision = next(item for item in result.decisions if item.rule == "deduplicate-and")
    assert decision.proofs
    assert all(proof.proven for proof in decision.proofs)
