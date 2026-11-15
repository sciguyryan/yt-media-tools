# Phase 6.5c residual legacy accounting

Every legacy test module carrying test functions is accounted below by surface
ownership, from the retirement audit inventory (224 files,
1640 test functions, 4134 assertion sites at accounting time).
Surfaces map onto the standing deferral registry from Phases 6.5a.1-6.5a.7;
portable migration for a surface proceeds when its fixture and contract
prerequisites exist, and implementation-owned surfaces remain Python by
policy. Function-surface modules are already fully dispositioned and
accounted in REVIEWED-RETIREMENTS.json (15 reviewed modules, 91 retained
tests, 74 reviewed retirements). Statement-surface obligations (DISTINCT,
ORDER BY, LIMIT/OFFSET, HAVING) are largely normative already, including the
corpus's first tied-order case (ordering.offset_limit) and the NULL placement
rule (ordering.order_nulls_last_asc/desc).

## relational: 38 modules

Facet, join, union, CTE, derived-relation and multi-source composition surfaces. The committed heterogeneous-sources-v1 and heterogeneous-facets-v1 datasets still have no normative cases; the facet/union/join test family migrates once those datasets are bound into the corpus (the largest outstanding portable surface). Key modules: test_join_* (execution, parser, predicates, projection, composition, conformance), test_cross_facet_composition, test_multi_source_facets, test_derived_relations, test_ctes, test_union_acquisition_planning, test_collection_* relational parts, test_torture_queries compositions.

- `python/yt_discover_tests/test_collection_cardinality_count.py`
- `python/yt_discover_tests/test_collection_element_scope_semantics.py`
- `python/yt_discover_tests/test_collection_export.py`
- `python/yt_discover_tests/test_collection_field_capabilities.py`
- `python/yt_discover_tests/test_collection_filtering.py`
- `python/yt_discover_tests/test_collection_index_acquisition_planning.py`
- `python/yt_discover_tests/test_collection_index_parser.py`
- `python/yt_discover_tests/test_collection_index_semantics.py`
- `python/yt_discover_tests/test_collection_predicate_evaluation.py`
- `python/yt_discover_tests/test_collection_predicate_parser.py`
- `python/yt_discover_tests/test_collection_projection.py`
- `python/yt_discover_tests/test_collection_query_acquisition_planning.py`
- `python/yt_discover_tests/test_collection_title_acquisition.py`
- `python/yt_discover_tests/test_collection_type_model.py`
- `python/yt_discover_tests/test_cross_facet_composition.py`
- `python/yt_discover_tests/test_cte_dependency_propagation.py`
- `python/yt_discover_tests/test_ctes.py`
- `python/yt_discover_tests/test_derived_relations.py`
- `python/yt_discover_tests/test_join_composition_planning.py`
- `python/yt_discover_tests/test_join_conformance_explain.py`
- `python/yt_discover_tests/test_join_existence_execution.py`
- `python/yt_discover_tests/test_join_existence_oracle.py`
- `python/yt_discover_tests/test_join_inner_execution.py`
- `python/yt_discover_tests/test_join_left_execution.py`
- `python/yt_discover_tests/test_join_parser.py`
- `python/yt_discover_tests/test_join_predicates.py`
- `python/yt_discover_tests/test_join_projection.py`
- `python/yt_discover_tests/test_join_relational_optimisation.py`
- `python/yt_discover_tests/test_multi_source_facets.py`
- `python/yt_discover_tests/test_projection.py`
- `python/yt_discover_tests/test_structured_member_acquisition_planning.py`
- `python/yt_discover_tests/test_structured_member_evaluation.py`
- `python/yt_discover_tests/test_structured_member_parser.py`
- `python/yt_discover_tests/test_structured_member_resolution.py`
- `python/yt_discover_tests/test_structured_metadata_schemas.py`
- `python/yt_discover_tests/test_structured_type_model.py`
- `python/yt_discover_tests/test_torture_queries.py`
- `python/yt_discover_tests/test_union_acquisition_planning.py`

## scalar: 5 modules

Scalar expression and row-shaping surfaces, including the OFFSET/LIMIT shaping tests. Nested compositions and field-argument coverage are normative (6.5a.2-6.5a.7, ordering.offset_limit and the ordering alias cases); the remaining tests are arithmetic-precedence, NULL-arithmetic, statement-shaping and required-field planner contracts retained with reasons in module_reviews.

- `python/yt_discover_tests/test_numeric_literals.py`
- `python/yt_discover_tests/test_row_shaping.py`
- `python/yt_discover_tests/test_row_slicing_integer_bases.py`
- `python/yt_discover_tests/test_scalar_expressions.py`
- `python/yt_discover_tests/test_scalar_extrema_functions.py`

## grammar: 1 modules

Formal grammar contract maintenance: grammar productions and diagnostic phrasing boundaries stay Python-owned; the portable contract certifies diagnostic categories only.

- `python/yt_discover_tests/test_language_validation.py`

## implementation: 21 modules

Optimiser, planner, parser-internals and provability frameworks: execution-path contracts explicitly retained by the migration policy, each with module_reviews reasons where the module is function-scoped and ledger dispositions otherwise.

- `python/yt_discover_tests/test_evaluation_context.py`
- `python/yt_discover_tests/test_formal_grammar_contract.py`
- `python/yt_discover_tests/test_identifier_case_sensitivity.py`
- `python/yt_discover_tests/test_identifier_keyword_contract.py`
- `python/yt_discover_tests/test_limit_termination.py`
- `python/yt_discover_tests/test_optimizer.py`
- `python/yt_discover_tests/test_optimizer_differential_corpus.py`
- `python/yt_discover_tests/test_optimizer_proofs.py`
- `python/yt_discover_tests/test_parser_differential_conformance.py`
- `python/yt_discover_tests/test_parser_formatter_boundary.py`
- `python/yt_discover_tests/test_parser_migration_equivalence.py`
- `python/yt_discover_tests/test_query.py`
- `python/yt_discover_tests/test_query_diagnostic_context.py`
- `python/yt_discover_tests/test_query_file_input.py`
- `python/yt_discover_tests/test_query_model.py`
- `python/yt_discover_tests/test_query_parameters.py`
- `python/yt_discover_tests/test_query_scope.py`
- `python/yt_discover_tests/test_query_traversal.py`
- `python/yt_discover_tests/test_semantic_property_framework.py`
- `python/yt_discover_tests/test_semantic_provability.py`
- `python/yt_discover_tests/test_static_relation_simplification.py`

## infrastructure: 55 modules

Cache, acquisition, CLI, backend, persistence, observability and freshness behaviour: not YT-SQL language semantics. Out of corpus scope permanently; retained as implementation tests.

- `python/yt_discover_tests/test_acquisition_plan.py`
- `python/yt_discover_tests/test_acquisition_progress.py`
- `python/yt_discover_tests/test_acquisition_torture.py`
- `python/yt_discover_tests/test_append_output.py`
- `python/yt_discover_tests/test_application_shell.py`
- `python/yt_discover_tests/test_backend_source_resolution.py`
- `python/yt_discover_tests/test_cache.py`
- `python/yt_discover_tests/test_cache_compaction.py`
- `python/yt_discover_tests/test_cache_discovery.py`
- `python/yt_discover_tests/test_cache_migration_console.py`
- `python/yt_discover_tests/test_cache_migration_support.py`
- `python/yt_discover_tests/test_cache_migration_transition_workflow.py`
- `python/yt_discover_tests/test_cache_migration_workflow.py`
- `python/yt_discover_tests/test_cache_migrations.py`
- `python/yt_discover_tests/test_cache_startup_execution.py`
- `python/yt_discover_tests/test_cache_startup_policy.py`
- `python/yt_discover_tests/test_cache_v3_contract.py`
- `python/yt_discover_tests/test_cache_v3_invalid_contract.py`
- `python/yt_discover_tests/test_cache_v3_oracle.py`
- `python/yt_discover_tests/test_cache_v3_to_v4_analysis.py`
- `python/yt_discover_tests/test_cache_v3_to_v4_historical.py`
- `python/yt_discover_tests/test_cache_v3_to_v4_migration.py`
- `python/yt_discover_tests/test_cache_v3_to_v4_verification.py`
- `python/yt_discover_tests/test_cache_v4_cross_source_reuse.py`
- `python/yt_discover_tests/test_cache_v4_entity_store.py`
- `python/yt_discover_tests/test_cache_v4_maintenance_execution.py`
- `python/yt_discover_tests/test_cache_v4_maintenance_plan.py`
- `python/yt_discover_tests/test_cache_v4_migration_reconciliation_benchmark.py`
- `python/yt_discover_tests/test_cache_v4_reconciliation_benchmark.py`
- `python/yt_discover_tests/test_cache_v4_registered_collections.py`
- `python/yt_discover_tests/test_cache_v4_registry_contract.py`
- `python/yt_discover_tests/test_cache_v4_registry_hardening.py`
- `python/yt_discover_tests/test_cache_v4_registry_resolution.py`
- `python/yt_discover_tests/test_cache_v4_registry_store.py`
- `python/yt_discover_tests/test_cache_v4_runtime_reconciliation_benchmark.py`
- `python/yt_discover_tests/test_cache_v4_source_bridge.py`
- `python/yt_discover_tests/test_cache_v4_status.py`
- `python/yt_discover_tests/test_capability_predicate_simplification.py`
- `python/yt_discover_tests/test_cli_metadata.py`
- `python/yt_discover_tests/test_cookie_translation.py`
- `python/yt_discover_tests/test_cost_planning.py`
- `python/yt_discover_tests/test_cost_selectivity_heuristics.py`
- `python/yt_discover_tests/test_explain.py`
- `python/yt_discover_tests/test_explain_presentation.py`
- `python/yt_discover_tests/test_external_tool_diagnostics.py`
- `python/yt_discover_tests/test_frontier_refresh.py`
- `python/yt_discover_tests/test_json_quality.py`
- `python/yt_discover_tests/test_metadata_requirement_pruning.py`
- `python/yt_discover_tests/test_observability.py`
- `python/yt_discover_tests/test_source_boundary_planning.py`
- `python/yt_discover_tests/test_source_capability_architecture.py`
- `python/yt_discover_tests/test_source_facets.py`
- `python/yt_discover_tests/test_source_resolution_contract.py`
- `python/yt_discover_tests/test_sources.py`
- `python/yt_discover_tests/test_staged_predicate_evaluation.py`

## harness: 53 modules

The portable harness's own test suite (staging, admission, comparators, validators, conformance runner, dashboard): guards the certification tooling itself, which Phase 7 depends on. Retained.

- `python/yt_discover_tests/test_conformance.py`
- `python/yt_discover_tests/test_portable_candidate_admission.py`
- `python/yt_discover_tests/test_portable_candidate_promotion.py`
- `python/yt_discover_tests/test_portable_candidate_review.py`
- `python/yt_discover_tests/test_portable_candidate_staging.py`
- `python/yt_discover_tests/test_portable_ci_report_workflow.py`
- `python/yt_discover_tests/test_portable_conformance_harness.py`
- `python/yt_discover_tests/test_portable_contract_reconciliation.py`
- `python/yt_discover_tests/test_portable_corpus_contract.py`
- `python/yt_discover_tests/test_portable_corpus_structure.py`
- `python/yt_discover_tests/test_portable_coverage_gap_matrix.py`
- `python/yt_discover_tests/test_portable_coverage_inventory.py`
- `python/yt_discover_tests/test_portable_dataset_export.py`
- `python/yt_discover_tests/test_portable_dataset_profiles.py`
- `python/yt_discover_tests/test_portable_dataset_validation.py`
- `python/yt_discover_tests/test_portable_diagnostics.py`
- `python/yt_discover_tests/test_portable_differential.py`
- `python/yt_discover_tests/test_portable_execution_config.py`
- `python/yt_discover_tests/test_portable_facet_topology.py`
- `python/yt_discover_tests/test_portable_final_contract.py`
- `python/yt_discover_tests/test_portable_fixture_checks.py`
- `python/yt_discover_tests/test_portable_fixture_relationships.py`
- `python/yt_discover_tests/test_portable_function_conformance_matrix.py`
- `python/yt_discover_tests/test_portable_function_semantic_audit.py`
- `python/yt_discover_tests/test_portable_grammar_candidate_review.py`
- `python/yt_discover_tests/test_portable_grammar_reconciliation.py`
- `python/yt_discover_tests/test_portable_language_element_registry.py`
- `python/yt_discover_tests/test_portable_language_surface_audit.py`
- `python/yt_discover_tests/test_portable_metamorphic.py`
- `python/yt_discover_tests/test_portable_operator_spelling_audit.py`
- `python/yt_discover_tests/test_portable_outcome_comparison.py`
- `python/yt_discover_tests/test_portable_parameters.py`
- `python/yt_discover_tests/test_portable_phase1_completeness.py`
- `python/yt_discover_tests/test_portable_phase1_coverage_assessment.py`
- `python/yt_discover_tests/test_portable_phase7_migration_proposal.py`
- `python/yt_discover_tests/test_portable_platform_parity.py`
- `python/yt_discover_tests/test_portable_python_candidate_adapter.py`
- `python/yt_discover_tests/test_portable_registry_reconciliation.py`
- `python/yt_discover_tests/test_portable_report_contract.py`
- `python/yt_discover_tests/test_portable_review_record.py`
- `python/yt_discover_tests/test_portable_schema_consistency.py`
- `python/yt_discover_tests/test_portable_semantic_retirement_audit.py`
- `python/yt_discover_tests/test_portable_semantic_surface_audit.py`
- `python/yt_discover_tests/test_portable_source_topology.py`
- `python/yt_discover_tests/test_portable_textual_predicate_audit.py`
- `python/yt_discover_tests/test_portable_tied_group_comparison.py`
- `python/yt_discover_tests/test_portable_tied_outcome_contract.py`
- `python/yt_discover_tests/test_portable_tied_slice_comparison.py`
- `python/yt_discover_tests/test_portable_tied_slice_exhaustive.py`
- `python/yt_discover_tests/test_portable_timestamp_precision.py`
- `python/yt_discover_tests/test_portable_torture_metamorphic.py`
- `python/yt_discover_tests/test_portable_typed_values.py`
- `python/yt_discover_tests/test_portable_unicode_fixture_audit.py`

## mixed: 49 modules

Modules spanning several of the above surfaces. Their per-test dispositions follow the owning surface's policy; each is individually listed for review.

- `python/yt_discover_tests/test_aggregation.py`
- `python/yt_discover_tests/test_boolean_short_circuit.py`
- `python/yt_discover_tests/test_canonical_formatting_contract.py`
- `python/yt_discover_tests/test_capabilities.py`
- `python/yt_discover_tests/test_case_expressions.py`
- `python/yt_discover_tests/test_char_function.py`
- `python/yt_discover_tests/test_compound_order_by.py`
- `python/yt_discover_tests/test_compound_query_grouping.py`
- `python/yt_discover_tests/test_concat_function.py`
- `python/yt_discover_tests/test_final_position_language.py`
- `python/yt_discover_tests/test_freshness_config.py`
- `python/yt_discover_tests/test_freshness_config_discovery.py`
- `python/yt_discover_tests/test_freshness_runtime.py`
- `python/yt_discover_tests/test_like_predicates.py`
- `python/yt_discover_tests/test_network_proxy.py`
- `python/yt_discover_tests/test_normative_unittest_integration.py`
- `python/yt_discover_tests/test_null_safe_comparison.py`
- `python/yt_discover_tests/test_offline_execution.py`
- `python/yt_discover_tests/test_order_by_resolution.py`
- `python/yt_discover_tests/test_ordering_type_baseline.py`
- `python/yt_discover_tests/test_planner.py`
- `python/yt_discover_tests/test_planner_boundaries.py`
- `python/yt_discover_tests/test_planning_analysis_reuse.py`
- `python/yt_discover_tests/test_precommit_cache.py`
- `python/yt_discover_tests/test_precommit_ysql_conformance.py`
- `python/yt_discover_tests/test_provenance.py`
- `python/yt_discover_tests/test_provider_capabilities.py`
- `python/yt_discover_tests/test_quoted_identifiers.py`
- `python/yt_discover_tests/test_random_function.py`
- `python/yt_discover_tests/test_relation_conformance_oracle.py`
- `python/yt_discover_tests/test_reserved_literal_words.py`
- `python/yt_discover_tests/test_resolver_evaluator_boundary.py`
- `python/yt_discover_tests/test_select_clause_grammar.py`
- `python/yt_discover_tests/test_select_compound_compatibility.py`
- `python/yt_discover_tests/test_set_operations.py`
- `python/yt_discover_tests/test_temporal_bound_frontier_inference.py`
- `python/yt_discover_tests/test_temporal_canonical_formatting.py`
- `python/yt_discover_tests/test_tools.py`
- `python/yt_discover_tests/test_truth_value_inspection.py`
- `python/yt_discover_tests/test_unicode_identifier_torture.py`
- `python/yt_discover_tests/test_unicode_identifiers.py`
- `python/yt_discover_tests/test_unicode_semantics.py`
- `python/yt_discover_tests/test_units.py`
- `python/yt_discover_tests/test_youtubejs_bridge_diagnostics.py`
- `python/yt_discover_tests/test_youtubejs_production_acquisition.py`
- `python/yt_discover_tests/test_youtubejs_publish_date.py`
- `python/yt_discover_tests/test_ytdlp_planning.py`
- `python/yt_discover_tests/test_ytmusicapi_production_acquisition.py`
- `python/yt_discover_tests/test_ytsql_query_to_case.py`
