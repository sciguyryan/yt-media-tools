# yt-sql operator surface audit

## Purpose

This document audits the current yt-sql operator surface against `YT-SQL-OPERATOR-DESIGN.md`. It is limited to operators and grammatical forms that behave as operators. It is not an audit of missing scalar, aggregate or media-specific functions.

The audit classifies meaningful candidates as supported, deliberately omitted or a genuine language gap. A genuine gap is not implemented here. It requires a separate implementation issue so syntax, semantics, precedence, NULL behaviour, optimisation and conformance can be reviewed independently before issue #10 closes.

## Current surface

The current expression and predicate surface is coherent across the main established families:

- numeric arithmetic: binary `+`, `-`, `*`, `/` and `%`, with unary `+` and `-`;
- ordinary comparison: `=`, `!=`, `<>`, `<`, `<=`, `>` and `>=`, plus the documented readable aliases;
- Boolean composition: `AND`, `OR` and unary `NOT` with observable left-to-right short-circuit semantics;
- range and membership: `BETWEEN`, `NOT BETWEEN`, `IN` and `NOT IN`;
- NULL and Boolean tests: `IS NULL`, `IS NOT NULL`, `IS TRUE`, `IS NOT TRUE`, `IS FALSE` and `IS NOT FALSE` on the currently supported field form;
- text predicates: `CONTAINS`, `MATCHES`, `LIKE` and `ILIKE`, including their negated forms;
- collection scope: `ANY` and `ALL` forms whose grammar exposes the element scope they introduce;
- relation and set structure: `JOIN`, `UNION`, grouping, ordering and related query grammar whose structural effects are intentionally visible.

The established families generally have their expected negated counterparts. Arithmetic precedence and Boolean precedence are conventional, and the existing specialised text predicates make their matching model clearer than symbolic aliases would.

## Genuine gap: NULL-safe equality and inequality

`IS DISTINCT FROM` and `IS NOT DISTINCT FROM` are genuine operator-level gaps. Ordinary `=` and `!=` deliberately produce UNKNOWN when either operand is NULL, while NULL-safe equality is a comparison semantic rather than an ordinary scalar transformation. Expressing it through combinations of equality, NULL tests and Boolean operators is verbose, easy to get wrong under three-valued logic and particularly awkward for general scalar expressions.

These forms therefore satisfy the operator-design criteria: they complete an existing comparison family, make materially different NULL semantics explicit at the point of comparison and improve readability without hiding evaluation scope. They should be implemented in a separate 0.29.6 issue before issue #10 closes. The implementation must define both forms together and cover arbitrary compatible scalar operands rather than only fields.

## Genuine gap: general truth-value tests

The current `IS TRUE`, `IS NOT TRUE`, `IS FALSE` and `IS NOT FALSE` forms are limited to the field-oriented predicate grammar. yt-sql now has a substantial Boolean expression language whose results may be TRUE, FALSE or UNKNOWN, but it has no general operator for testing the truth value of an arbitrary predicate expression and no `IS UNKNOWN` / `IS NOT UNKNOWN` form.

This is a genuine coherence gap rather than a request for a new function. A separate 0.29.6 implementation issue should generalise truth-value tests over Boolean predicate expressions and complete the family with UNKNOWN. The design must preserve the distinction between three-valued Boolean evaluation and truth-value inspection: every `IS [NOT] TRUE|FALSE|UNKNOWN` test itself returns TRUE or FALSE, including when its operand is UNKNOWN.

## Deliberate omissions

The audit does not find justification for additional symbolic arithmetic, Boolean or text operators. Exponentiation is an ordinary numeric value operation and does not require an operator merely to shorten a function form. Bitwise operators do not currently have a demonstrated media-query need. Boolean XOR is expressible from the existing Boolean language and does not provide structural semantics that justify another precedence level. Symbolic string concatenation would duplicate an ordinary value transformation, and symbolic regular-expression or containment aliases would make the existing named predicate semantics less discoverable rather than more so.

Null coalescence remains deliberately omitted as an operator. `COALESCE(...)` expresses the value transformation directly, and `??` would add grammar primarily for brevity. No finding in this audit changes that Phase 1 decision.

## Structural and future forms

Scope-changing collection forms and relation-shaping operations remain grammar by design. Future sequence or source/facet proposals should be assessed when their semantics are specified because their justification depends on whether they genuinely change scope, ordering or relation structure. Their existence on a future roadmap is not evidence that an operator is currently missing.

The audit does not use SQL completeness as a target. An operator present in another SQL dialect is not a yt-sql gap unless the missing operation also satisfies the project policy and fills a concrete semantic or coherence hole in yt-sql.

## Findings

Two implementation defects block final reconciliation of issue #10:

1. NULL-safe comparison needs `IS DISTINCT FROM` and `IS NOT DISTINCT FROM`.
2. Truth-value inspection needs to apply to general Boolean predicate expressions and include `IS UNKNOWN` and `IS NOT UNKNOWN`.

Both should be implemented as separate issues before the final operator-design reconciliation. No other operator-level defect was identified by this audit, and missing functions are explicitly outside its scope.
