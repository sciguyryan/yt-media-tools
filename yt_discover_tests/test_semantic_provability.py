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


def test_shared_predicate_prover_composes_never_true_or_branches() -> None:
    predicate = parse_query(
        "SELECT id FROM @x WHERE (view_count = 5 AND view_count > 10) OR (duration < 1 AND duration >= 1)"
    ).predicate
    proof = prove_predicate_never_true(predicate, source=None)
    assert proof is not None and proof.proven
    assert "both OR branches" in proof.reasons[0]
    assert len(proof.premises) == 2


def test_shared_predicate_prover_refuses_or_with_one_live_branch() -> None:
    predicate = parse_query("SELECT id FROM @x WHERE (view_count = 5 AND view_count > 10) OR duration > 1").predicate
    assert prove_predicate_never_true(predicate, source=None) is None


def test_shared_predicate_prover_handles_reversed_and_exclusion_constraints() -> None:
    reversed_bounds = parse_query("SELECT id FROM @x WHERE 10 < view_count AND view_count <= 10").predicate
    excluded_equality = parse_query("SELECT id FROM @x WHERE view_count = 5 AND view_count != 5").predicate
    assert prove_predicate_never_true(reversed_bounds, source=None) is not None
    assert prove_predicate_never_true(excluded_equality, source=None) is not None


def test_shared_predicate_prover_handles_finite_in_domains_conservatively() -> None:
    outside = parse_query("SELECT id FROM @x WHERE view_count = 5 AND view_count IN (1, 2, 3)").predicate
    disjoint = parse_query("SELECT id FROM @x WHERE view_count IN (1, 2) AND view_count IN (3, 4)").predicate
    overlap = parse_query("SELECT id FROM @x WHERE view_count IN (1, 2) AND view_count IN (2, 3)").predicate
    assert prove_predicate_never_true(outside, source=None) is not None
    assert prove_predicate_never_true(disjoint, source=None) is not None
    assert prove_predicate_never_true(overlap, source=None) is None


def test_shared_predicate_prover_handles_positive_between_bounds() -> None:
    predicate = parse_query("SELECT id FROM @x WHERE view_count BETWEEN 1 AND 5 AND view_count > 5").predicate
    compatible = parse_query("SELECT id FROM @x WHERE view_count BETWEEN 1 AND 5 AND view_count >= 5").predicate
    assert prove_predicate_never_true(predicate, source=None) is not None
    assert prove_predicate_never_true(compatible, source=None) is None


def test_relation_facts_propagate_empty_cte_into_primary_relation() -> None:
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    query = parse_query(
        "WITH empty AS (SELECT id FROM @x WHERE view_count = 5 AND view_count > 10) SELECT id FROM empty"
    )
    facts = prove_query_relation_facts(query)
    assert facts.empty and facts.max_rows == 0
    assert facts.proof is not None and facts.proof.premises


def test_relation_facts_require_every_union_branch_to_be_empty() -> None:
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    empty = parse_query(
        "SELECT id FROM @x WHERE 1 = 0 UNION ALL SELECT id FROM @y WHERE duration < 1 AND duration >= 1"
    )
    live = parse_query("SELECT id FROM @x WHERE 1 = 0 UNION ALL SELECT id FROM @y WHERE duration > 1")
    assert prove_query_relation_facts(empty).empty
    assert not prove_query_relation_facts(live).empty


def test_relation_facts_propagate_empty_right_cte_by_join_semantics() -> None:
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    inner = parse_query(
        "WITH empty AS (SELECT id FROM @right WHERE 1 = 0) SELECT l.id FROM @left AS l JOIN empty AS r ON l.id = r.id"
    )
    left = parse_query(
        "WITH empty AS (SELECT id FROM @right WHERE 1 = 0) "
        "SELECT l.id FROM @left AS l LEFT JOIN empty AS r ON l.id = r.id"
    )
    assert prove_query_relation_facts(inner).empty
    assert not prove_query_relation_facts(left).empty


def test_relation_facts_use_only_explicit_cardinality_bounds() -> None:
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    limited = prove_query_relation_facts(parse_query("SELECT id FROM @x LIMIT 7"))
    unknown = prove_query_relation_facts(parse_query("SELECT id FROM @x"))
    assert limited.max_rows == 7 and not limited.empty
    assert unknown.max_rows is None and not unknown.empty


def test_relation_facts_state_current_nullability_and_cardinality_boundaries() -> None:
    from yt_media_tools.semantic_provability import prove_query_relation_facts

    facts = prove_query_relation_facts(parse_query("SELECT id, title FROM @x"))
    assert not facts.empty
    assert any("nullability" in boundary for boundary in facts.boundaries)
    assert any("physical-source cardinality" in boundary for boundary in facts.boundaries)
