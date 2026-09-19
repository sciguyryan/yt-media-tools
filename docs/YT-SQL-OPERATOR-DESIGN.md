# yt-sql operator design

## Purpose

This document defines the criteria used to decide whether an operation deserves dedicated yt-sql operator syntax. It is a design policy for operators, not a catalogue of functions that the language should add.

The central rule is that new grammar must buy semantic or structural clarity, not merely brevity. An operation should not receive dedicated syntax solely because an operator spelling is shorter than an existing function call.

## Structural operations

Operations that introduce or change name resolution, element scope, relation scope, evaluation context or relation shape should normally be expressed by grammar. Hiding structural behaviour inside an ordinary function call makes scope and evaluation rules harder to see at the point of use.

Relation-shaping operations such as `JOIN`, `UNION`, `GROUP BY` and `ORDER BY` therefore belong to the grammatical language surface. The same principle applies to future proposals whose meaning depends on introducing a scope or changing which relation or collection an expression is evaluated against.

## Value operations

Ordinary value transformations should normally remain scalar functions when their arguments are explicit and their evaluation does not alter scope or relation structure. Dedicated operator syntax is justified only when it provides a material improvement in semantic clarity, readability, predictability or discoverability rather than a shorter spelling alone.

Aggregation over an already established group or collection should normally remain aggregate-function syntax unless the proposed operation itself changes relation structure or evaluation scope. Media-specific value operations should likewise prefer clearly named functions when they express a domain concept directly without requiring new general-purpose language machinery.

## Operator review criteria

A proposed operator should be reviewed against all of the following questions:

1. Does the operation change relation structure?
2. Does it introduce or change name resolution, element scope, relation scope or evaluation context?
3. Can an ordinary expression or function express it without hiding structural semantics?
4. Is it aggregation over an existing group or collection rather than a relation transformation?
5. Is it a media-specific value operation that a named function would express more directly?
6. Is the operation common enough that dedicated syntax materially improves readability or discoverability?
7. Does the proposed syntax compose predictably with existing operators and grammatical forms?
8. What precedence, associativity, ambiguity and parser complexity would the syntax introduce?
9. Does the syntax make the operation's semantics clearer, or does it merely use fewer characters?

These questions are design criteria rather than mechanical rules. Scope-changing and relation-shaping semantics create a strong presumption in favour of grammar. Ordinary value transformation and aggregation create a strong presumption in favour of functions. Parser complexity is a real cost, but it is secondary to a clear representation of genuinely structural semantics.

## Readability and discoverability

Readability, predictability and discoverability are primary considerations for operations users are likely to write frequently. Familiar syntax may help, but compatibility with another SQL dialect is not independently sufficient reason to add an operator.

A proposal should be understandable in the context of yt-sql itself. New syntax should fit the existing precedence model, avoid surprising interactions with neighbouring operators and remain practical to document, diagnose, format and test.

## Deliberate negative example: null coalescence

Null coalescence does not currently justify dedicated operator syntax such as:

``` sql
title ?? "Missing"
```

The existing form is explicit and already expresses the operation as an ordinary scalar value transformation:

``` sql
COALESCE(title, "Missing")
```

The operation does not change scope, name resolution, relation shape or evaluation context. The shorter operator spelling would therefore add grammar primarily for brevity rather than to expose structural semantics. `??` is not planned under this policy.

## Applying the policy

The policy should be applied to new operator proposals before implementation work begins. A proposal may still be rejected when it passes one criterion if its overall benefit does not justify the additional language surface, and existing coherent syntax should not be rewritten merely because this policy might have produced a different design if it had existed earlier.

When a review identifies a genuine missing operator, implementation should be tracked separately with its syntax, precedence, typing, NULL behaviour, evaluation semantics, optimiser implications, diagnostics and conformance requirements made explicit. Operator-design reviews should not silently grow into implementation work.

The current operator-surface audit is recorded in `YT-SQL-OPERATOR-AUDIT.md`.
