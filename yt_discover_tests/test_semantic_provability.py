"""Shared semantic and relational provability coverage."""

from yt_media_tools.optimizer_proofs import proof_to_dict
from yt_media_tools.query import parse_query
from yt_media_tools.semantic_provability import prove_join_consequences, prove_predicate_never_true


def test_shared_predicate_prover_establishes_constant_rejection_with_provenance() -> None:
    predicate = parse_query("SELECT id FROM @x WHERE 1 = 0").predicate
    proof = prove_predicate_never_true(predicate, source=None)
    assert proof is not None and proof.proven
    payload = proof_to_dict(proof)
    assert payload["claim"] == "predicate-never-true"
    assert payload["premises"]


def test_shared_predicate_prover_establishes_same_field_contradiction() -> None:
    predicate = parse_query("SELECT id FROM @x WHERE view_count = 5 AND view_count > 10").predicate
    proof = prove_predicate_never_true(predicate, source=None)
    assert proof is not None and proof.proven
    assert "incompatible with its lower bound" in proof.reasons[0]


def test_shared_predicate_prover_refuses_non_contradictory_dynamic_predicate() -> None:
    predicate = parse_query("SELECT id FROM @x WHERE view_count > 5 AND duration > 10").predicate
    assert prove_predicate_never_true(predicate, source=None) is None


def test_join_consequences_separate_proof_from_operator_policy() -> None:
    predicate = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON 1 = 0").joins[0].predicate
    inner = prove_join_consequences("INNER", predicate)
    left = prove_join_consequences("LEFT", predicate)
    assert inner.predicate_never_true and inner.result_empty and inner.right_relation_irrelevant
    assert left.predicate_never_true and not left.result_empty and left.right_relation_irrelevant
    assert inner.proof is not None and inner.proof.premises


def test_join_prover_refuses_row_dependent_equality() -> None:
    predicate = parse_query("SELECT l.id FROM @left AS l JOIN @right AS r ON l.id = r.id").joins[0].predicate
    proof = prove_join_consequences("INNER", predicate)
    assert not proof.predicate_never_true
    assert proof.proof is None


def test_boolean_reachability_requires_a_dominating_left_operand() -> None:
    from yt_media_tools.semantic_provability import prove_boolean_right_unreachable

    false_and = parse_query("SELECT id FROM @x WHERE 1 = 0 AND view_count > 10").predicate
    true_or = parse_query("SELECT id FROM @x WHERE 1 = 1 OR view_count > 10").predicate
    right_false = parse_query("SELECT id FROM @x WHERE view_count > 10 AND 1 = 0").predicate
    right_true = parse_query("SELECT id FROM @x WHERE view_count > 10 OR 1 = 1").predicate
    unknown_and = parse_query("SELECT id FROM @x WHERE 1 = NULL AND view_count > 10").predicate

    assert prove_boolean_right_unreachable(false_and, source=None) is not None
    assert prove_boolean_right_unreachable(true_or, source=None) is not None
    assert prove_boolean_right_unreachable(right_false, source=None) is None
    assert prove_boolean_right_unreachable(right_true, source=None) is None
    assert prove_boolean_right_unreachable(unknown_and, source=None) is None
