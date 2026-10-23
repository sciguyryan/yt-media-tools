# Phase 1 language registry reconciliation

This review reconciles the source-derived grammar and operator investigations with the curated language-element registry. It is a language-surface classification, not conformance certification.

The registry now contains 19 previously unregistered supported keyword candidates and five symbolic operator spellings. Each remains pending and has no approved case association. The `*` token is used in multiple contexts, including wildcard syntax, so one operator entry does not discharge its separate syntax coverage obligations.

The parser explicitly recognises `CROSS`, `FULL`, `NATURAL`, `RECURSIVE` and `RIGHT` in unsupported grammar contexts. They remain outside the supported keyword registry and require reviewed negative cases. The spelling probes do not establish support for `&&`, `||`, `!` or `==`, so none has been added.

The source classifications are checked by `reconcile_language_elements.py`, and `LANGUAGE-REGISTRY-RECONCILIATION.json` is a reproducible review record. A new candidate causes drift requiring a deliberate classification change. The existing assessment and registry audits continue to distinguish registered language elements from approved conformance coverage.

The next work should audit function arity and type rejection paths, establish explicit syntax alternatives beyond isolated keywords, and complete the Phase 1 exit criteria. Expected results generated from Python must still be reviewed before they become normative; this policy does not specify the reviewer or method.

## Function and semantic rejection investigation

Run `python yt-sql/build_function_semantic_audit.py` to regenerate `FUNCTION-SEMANTIC-AUDIT.json`, or add `--check` to detect drift. The audit enumerates every registered scalar and aggregate function with its previously reviewed parser argument shape, and identifies structural exception sites in the hand-written parser, resolver and evaluator. The output is an investigation index only. Function typing, nullability, coercion, boundaries, invalid arguments and diagnostic intent require deliberate review before normative conformance expectations can be approved. No particular review actor or mechanism is prescribed.
