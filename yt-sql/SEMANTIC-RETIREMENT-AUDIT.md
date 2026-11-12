# Semantic inventory and legacy retirement mapping

This audit establishes a traceable starting point for the final YT-SQL conformance migration. It inventories the current language registry, normative portable cases, Python test functions and their static assertion sites. It **does not** establish that an assertion is equivalent to a portable case, or that a language element has been exhaustively tested.

The generated `SEMANTIC-RETIREMENT-AUDIT.json` records each registered language element and its seven applicable coverage obligations, alongside every discovered legacy Python test function and the kinds of its assertion sites. It retains the previous file-level classifications for context. Those classifications are not retirement authorisations. A test file can contain both language semantics and implementation-specific checks; its functions and assertions must be reviewed separately.

The generated report records current counts for registered elements, portable manifests, Python test modules, test functions and assertion sites. These are discovery counts, not numbers of verified semantic obligations. Static inspection can miss implicit assertions (for example, calls that raise unexpectedly), and a single assertion can exercise several behaviours. The registry must also be extended if subsequent source review reveals unregistered supported behaviour.

## Retirement decisions

Legacy test functions remain retained pending assertion-level review unless their reviewed replacements are explicitly recorded in `REVIEWED-RETIREMENTS.json`. The migration review must identify the behaviour each assertion protects, associate it with one or more independently authored normative JSON expectations, and record actual execution and review evidence. A similar query, matching feature tag or passing differential run is insufficient to prove equivalent coverage. Assertions that protect planner internals, backend integration, acquisition, cache behaviour, CLI contracts or the conformance harness should remain in appropriate implementation-specific suites.

For every applicable coverage dimension, reviewers must either supply independently reviewed evidence or document why the dimension does not apply. Negative syntax, NULL and type semantics, boundaries, complex interactions and adversarial cases require explicit treatment. The current registry and completion plan have not yet certified those obligations; the audit deliberately leaves them pending rather than manufacturing coverage from the 107 approved manifests.

## Maintenance

Regenerate the report after changes to test discovery, the language registry, the completion plan or the normative case manifests:

```bash
python yt-sql/build_coverage_inventory.py
python yt-sql/build_semantic_retirement_audit.py
```

Use `--check` with each generator for drift detection. The semantic retirement report is a migration worklist for Phases 6.2–6.5, not a completion certificate. The first reviewed retirement batch is documented in `PHASE6-5-RETIREMENT-PASS.md`; all other legacy assertions remain pending review. Phase 6.6 must independently reconcile the final evidence, including any newly discovered language elements and documented exceptions.
