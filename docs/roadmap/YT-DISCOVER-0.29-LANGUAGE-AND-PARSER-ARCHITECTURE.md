# yt-discover 0.29.x - Language and Parser Architecture

## Purpose

The 0.29.x series is a comprehensive review and settlement of yt-sql language design followed by an evidence-driven parser architecture decision. It creates a stable language foundation before the broader feature programme resumes in 0.30.x.

The series must answer language-shape questions before attempting a parser rewrite. Agreed syntax and semantic changes should first be implemented and accepted through the existing parser so that the mature hand-written parser remains a behavioural reference for any replacement. Once those foundations are settled, the grammar freezes for the parser migration and no unrelated language expansion should occur until the parser decision and any migration are complete.

The roadmap is living. The questions and release decomposition below may be refined as review exposes dependencies, but parser migration must remain downstream of language settlement.

## Decision process

Each design topic moves through explicit states:

- **Under review**: the question is open and alternatives are being evaluated.
- **Accepted**: the project has selected the stated conclusion and it may be scheduled for implementation.
- **Rejected**: the project has considered and declined the proposal; the rationale should remain recorded so the same question is not repeatedly reopened without new evidence.
- **Deferred**: the question is valid but does not need to be settled for the parser foundation or current programme.

A design conclusion should record the reasoning that materially affected the decision. Accepted language changes should then receive a GitHub issue with concrete implementation and acceptance criteria. Discussion alone does not make a syntax proposal part of yt-sql.

## Accepted programme decisions

### 0.29.x owns language and parser architecture

**Status: Accepted**

0.29.x is reserved for the comprehensive language review, implementation of parser-foundational language decisions, formal grammar work, parser evaluation, differential reconciliation, and any justified parser migration. The former 0.29.x feature programme moves to 0.30.x, the former 0.30.x relational programme moves to 0.31.x, and the former 0.31.x usability programme moves to 0.32.x.

Accepted release history through 0.28.13 is unchanged. Completed series are release history rather than active roadmap items and do not need to remain under `docs/roadmap/` when their durable release record and current architecture are documented elsewhere.

### Settle language foundations before parser migration

**Status: Accepted**

The project will not rewrite the parser while material language-shape questions remain unresolved. Parser-affecting decisions are reviewed first. Accepted changes are implemented using the existing parser and covered by the normal semantic, optimiser, formatter, conformance, diagnostic and regression tests. Only after those changes are accepted does the language grammar freeze for parser migration.

During the parser migration sub-phase, new operators, clauses, collection syntax, precedence changes and unrelated grammar clean-ups are frozen. Genuine parser bugs may still be fixed, but language evolution resumes only after the parser architecture is accepted.

### Parser replacement is an investigation, not a predetermined outcome

**Status: Accepted**

The hand-written parser remains the canonical behavioural reference until evidence supports a replacement. Lark is the leading parser-library candidate for the first prototype, with another parser approach considered only where comparison adds useful evidence. The project may retain the hand-written parser if a declarative parser does not provide a clear improvement in maintainability, diagnostics, correctness and future extensibility.

A parser library must produce yt-sql's own model and diagnostics. Library-specific parse-tree or exception types must not leak into the resolver, evaluator, optimiser, acquisition planner, formatter, CLI or other semantic layers.

### Formal grammar as a first-class artefact

**Status: Accepted**

Regardless of whether the hand-written parser or a parser library ultimately wins, yt-sql should have an explicit formal grammar or equivalent grammar specification that documents the accepted syntax, precedence, associativity, lexical rules and extension points. The executable parser must remain consistent with that specification through automated tests.

## Language questions to settle

### Expression hierarchy and postfix syntax

**Status: Under review**

Define the complete expression precedence and associativity hierarchy and decide which postfix forms yt-sql should support. This includes whether indexing, structured member access or other postfix operations become general scalar-expression syntax and how they compose with function calls, CASE, parameters, arithmetic, comparisons and Boolean expressions.

The conclusion must avoid syntax that is easy to parse but difficult to type, optimise, acquire or explain.

### Typed collections and indexing

**Status: Under review**

Decide whether media metadata collections become first-class typed yt-sql values and whether direct indexing such as `tags[0]` is part of that model.

The review must cover at least tags, categories, formats, subtitles/captions, chapters and thumbnails, while distinguishing scalar collections from collections of structured records. It must decide indexing base, out-of-range behaviour, NULL collection behaviour, NULL elements, negative indexing, dynamic `raw.*` interaction, string indexing, acquisition requirements, element typing and whether slicing belongs in the language.

Do not implement `tags[0]` as an isolated special case. If indexing is accepted, it should arise from a coherent collection model.

### Structured metadata and member access

**Status: Under review**

Decide whether structured collection elements or metadata objects support member access such as `formats[0].height`, whether structured values have explicit schemas, and how unknown or backend-specific fields are represented. The design must preserve capability-aware acquisition and must not make provider-specific dictionaries the language's semantic model.

### Future relational composition and JOIN grammar

**Status: Under review**

Decide whether JOIN belongs in yt-sql's long-term language and, if accepted, settle the parser-facing relational syntax during 0.29.x while deferring full relational execution semantics to the later 0.31.x Relational Reconsideration programme. The parser review must consider JOIN kinds, relation aliases, qualified field references, `ON` predicates, source/facet participation, interaction with CTEs and set operations, `*` expansion, ambiguity handling and the relationship between qualified names and structured member access.

This question is coupled to expression hierarchy, postfix syntax and structured metadata. Syntax such as `a.title` may represent relation qualification while syntax such as `formats[0].height` may represent structured member access. The grammar and AST must preserve enough structure for semantic resolution to distinguish these cases without making provider-specific object layouts part of yt-sql semantics.

If JOIN is accepted as a future language capability, 0.29.x may introduce its stable grammar and AST representation before relational execution exists. In that case, semantic validation must reject executable JOIN queries clearly and deterministically until the later relational programme implements and validates acquisition, cardinality, NULL-extension, provenance, optimisation, evaluation and other relational semantics. Parser recognition must not imply executable feature support.

The review must also decide which relational forms should remain possible later. It must not assume that accepting a JOIN grammar commits yt-sql to general SQL JOIN completeness. Constrained forms such as SEMI and ANTI joins remain especially relevant to media-discovery use cases, but their eventual execution semantics belong to 0.31.x unless the living roadmap is deliberately revised again.

### Collection predicates, quantifiers and media-native operations

**Status: Under review**

Decide how users query collections beyond direct indexing. Compare general collection operations with media-native constructs such as `HAS_FORMAT(...)`, `COUNT_FORMATS(...)`, `FORMAT_MAX(...)` and `FORMAT_MIN(...)`. Avoid importing general-purpose lambda or array-language complexity unless concrete media-discovery use cases justify it.

### NULL coalescing

**Status: Under review**

Review a universal scalar `??` operator such as `title ?? "Missing Title"`. The current preferred semantic direction is SQL-NULL-only coalescing, with empty string, zero and FALSE remaining ordinary values. The review must settle precedence, associativity, chaining, type resolution, interaction with CASE and `COALESCE`, evaluation and volatility guarantees, optimiser rewrites, canonical formatting and diagnostics.

### Boolean short-circuit evaluation

**Status: Under review**

Decide whether AND and OR gain left-to-right short-circuit evaluation while preserving SQL three-valued logic. Evaluation order and optimiser predicate reordering are separate concerns and must remain separately specified. The decision must account for volatile expressions, errors, NULL/UNKNOWN semantics and observable evaluation behaviour.

### Operators and comparison semantics

**Status: Under review**

Review missing comparison, conversion, null-safe and media-useful operators before the grammar freezes. Conventional SQL syntax should be adopted only where it improves yt-sql rather than for compatibility completeness.

### Clause and compound-query grammar

**Status: Under review**

Review SELECT clause ordering, CTE composition, set operations, ORDER BY, LIMIT/OFFSET placement and whether compound queries need an explicit outer row-shaping model. Existing unusual syntax should be retained when it is coherent, but historical accident alone is not sufficient reason to preserve an awkward grammar before the parser architecture is frozen.

### Function syntax versus dedicated language syntax

**Status: Under review**

Review which behaviours deserve operators or dedicated grammar and which should remain ordinary scalar, aggregate or media-specific functions. Prefer a smaller coherent grammar when functions express the semantics clearly.

### Source, facet and future backend syntax

**Status: Under review**

Reconfirm the long-term source and facet grammar, including `OF`, and identify any language-level requirements implied by future multi-backend acquisition. Backend choice itself should remain a physical planning concern unless a concrete query semantic requires user-visible syntax.

### Temporal syntax

**Status: Under review**

Reconfirm durations, relative temporal expressions, date/timestamp literals and typed infinity sentinels. Resolve lexical or precedence ambiguities before formal grammar freeze without weakening the deterministic query-captured temporal model.

### Numeric, string and literal syntax

**Status: Under review**

Reconfirm decimal, hexadecimal, octal and binary integer literals, numeric separators, strings and escaping, NULL, TRUE/FALSE and parameters. Identify any lexical inconsistencies that would unnecessarily complicate a declarative grammar or future extension.

### Identifiers and keyword policy

**Status: Under review**

Define case sensitivity, keyword reservation, future keyword introduction, Unicode identifier behaviour and whether quoted identifiers are useful. The policy should minimise unnecessary future compatibility traps without turning yt-sql into a general SQL dialect.

### Staged grammar capability and executable capability

**Status: Accepted**

A syntax form may have a stable grammar and AST representation before its executable semantics are implemented when doing so materially reduces future parser churn. This exception should be used sparingly. Any such syntax must be rejected by semantic validation with a clear deterministic diagnostic until its execution semantics are implemented. Parser acceptance alone must never be documented or presented as executable language support. Future JOIN syntax is the principal current case under consideration for this staged approach.

### Parser diagnostics and source spans

**Status: Under review**

Define the stable yt-sql parser diagnostic contract, including syntax versus semantic errors, source positions and spans, expected-token reporting, contextual help and whether limited recovery or multiple-error reporting adds enough value. Parser-library exception wording must not become the public contract accidentally.

### Canonical formatting and parser round trips

**Status: Under review**

Every accepted syntax change must define a canonical representation. Parser and formatter behaviour should support deterministic parse-format-parse reconciliation, with semantic equivalence and structural stability tested where appropriate.

## Parser investigation after language settlement

The parser investigation begins only after the preceding parser-foundational questions are settled and all accepted language changes that materially affect the target grammar are implemented through the existing parser.

The investigation should then:

1. Freeze the accepted hand-written parser and target grammar as the behavioural reference.
2. Formalise the complete accepted grammar and parser contract.
3. Build a parser differential and diagnostic conformance harness before cutover.
4. Prototype Lark against the accepted grammar without adding new language features.
5. Produce the existing yt-sql AST/query model rather than introducing a second semantic representation.
6. Differentially compare valid syntax, precedence, model structure, literals, source positions, malformed input, deterministic diagnostics where appropriate and formatter round trips.
7. Use generated valid and invalid syntax plus focused fuzzing where it exposes parser classes that fixtures may miss.
8. Benchmark realistic and pathological query sizes and startup behaviour.
9. Evaluate dependency health, supported Python versions and operational packaging cost.
10. Make an explicit keep-or-migrate decision from the evidence.

If migration is accepted, make the declarative parser canonical only after differential reconciliation passes. Remove transitional parser infrastructure once it no longer provides useful regression protection. If migration is rejected, retain the hand-written parser, remove experimental implementation code, and keep the formal grammar, parser contract and improved conformance tests.

## GitHub issue workflow for 0.29.x

Design discussion precedes implementation issues. Once a language question reaches **Accepted**, raise a focused GitHub issue containing the conclusion, rationale, implementation scope, compatibility considerations, required documentation and automated acceptance criteria. A coherent design topic should normally be one issue with a checklist rather than many tiny issues.

The parser investigation should have an umbrella issue that does not presuppose migration. Candidate title: `Investigate declarative parser architecture for yt-sql`. Supporting issues may cover the formal grammar/parser contract, differential harness, Lark prototype, performance/diagnostic comparison, and final migration only if approved.

Commit or pull-request closure references such as `Closes #123` should be used only when the associated work genuinely completes the issue.

## Completion criteria

The 0.29.x programme is complete when:

- all parser-foundational language questions, including future relational-composition compatibility, are explicitly accepted, rejected or deferred with rationale;
- all accepted grammar-affecting language changes required before migration are implemented and accepted through the reference parser;
- the target grammar and parser contract are explicit and tested;
- the parser differential and diagnostic conformance harness is comprehensive enough to detect meaningful behavioural drift;
- the parser-library investigation has produced an evidence-based keep-or-migrate decision;
- any accepted migration has been reconciled against the reference parser and transitional scaffolding has been cleaned up;
- documentation accurately describes the resulting language and parser architecture;
- the 0.30.x feature programme can proceed without unresolved parser-foundational questions.

## Roadmap maintenance

This document is a living roadmap and decision record. Future 0.29.x release numbers should be assigned only when a reviewed topic has enough definition to form a coherent implementation and acceptance unit. Do not force every discussion topic into its own release, and do not preserve speculative phase numbering when the dependency structure suggests a better sequence.
