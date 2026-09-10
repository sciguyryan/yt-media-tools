# yt-discover 0.30.x - Relational Reconsideration

## Purpose

The 0.30.x series reconsiders selected relational composition after the
0.27.x refactor, 0.28.x acquisition-aware optimiser work, and 0.29.x
language and media-metadata expansion.

JOIN was previously excluded because Discover primarily operated over
one logical yt-dlp result stream. In that model there was rarely a
meaningful independent relation to join, and implementing JOIN merely
for SQL familiarity would have added parser, execution, cardinality and
acquisition complexity without enough practical value.

That premise no longer holds. Discover now has, or is planned to have,
independently acquired physical sources, logical source/facet identity,
CTEs, set composition, typed nested media collections, explicit
acquisition planning and source-aware optimisation. Selected join forms
can therefore express useful media discovery operations that are
otherwise awkward or lossy.

The purpose of this series is not SQL completeness. It is to add only
relational composition that materially increases Discover's ability to
combine and filter independently acquired media relations.

## Guiding example

A compelling motivating query is selecting every video from a channel
except videos already present in a particular playlist.

The identity-only form can use set difference:

``` sql
SELECT id
FROM @channel OF videos

EXCEPT

SELECT id
FROM @playlist
```

Retaining the complete channel-side row while using the playlist only as
an exclusion relation is naturally expressed as an anti join:

``` sql
SELECT v.*
FROM @channel OF videos AS v
ANTI JOIN @playlist AS p
    ON v.id = p.id
```

The playlist side may need only media identity. The planner can
potentially acquire playlist IDs, build an efficient membership
structure, enumerate the channel, discard matches immediately, and
acquire deeper metadata only for surviving channel rows.

This is the model against which join design should be judged: expressive
media discovery coupled to safe reduction of yt-dlp acquisition work.

## Programme invariants

-   Add joins for demonstrated Discover use cases, not SQL completeness.
-   Preserve explicit deterministic source and facet identity.
-   Preserve provenance for independently acquired relations.
-   Preserve SQL NULL semantics.
-   Never treat not-yet-acquired metadata as SQL NULL.
-   Type-check heterogeneous extractor schemas.
-   Make join planning participate in the acquisition optimiser.
-   Request the minimum metadata required from each side where possible.
-   Never duplicate, eliminate or reorder volatile expressions unsafely.
-   Keep query results independent of incidental acquisition order.
-   Compose joins predictably with CTEs, set operations, aggregates,
    windows, DISTINCT, ORDER BY, OFFSET and LIMIT.
-   Keep controlled expansion of a media row's nested collections
    conceptually distinct from joining independent relations.
-   Do not add Cartesian products merely because conventional SQL
    supports them.
-   Give every supported join form deterministic conformance,
    malformed-input, NULL, composition and optimiser-differential
    coverage.

## 0.30.0 - Join semantics and relation identity

Define the relational model before executable join syntax.

Specify joinable relations, aliases, field qualification and ambiguity,
provenance, row identity, schema construction, duplicate/cardinality
behaviour, NULL extension, dynamic fields, typed child collections and
deterministic output.

Define whether CTEs, physical source/facet queries, set-expression
results and expanded media collections may participate in relevant join
forms.

Keep child-collection expansion separate from ordinary joins unless a
later phase proves a unified model improves semantics without enabling
accidental Cartesian behaviour.

### Completion criteria

-   Written join semantic contract.
-   Parser/resolver design tests before execution support.
-   Deterministic ambiguity errors.
-   No regression to existing unqualified single-relation queries.
-   Explicit relation identity and provenance documentation.

## 0.30.1 - Join key and predicate analysis

Extend semantic property analysis to join conditions.

Classify stable-identity equality, ordinary scalar equality, composite
equality, range/inequality comparison, NULL sensitivity, determinism,
volatility, acquisition level and source/facet capability requirements.

Identify predicates evaluable from enumeration metadata and predicates
requiring deeper acquisition.

Do not expose arbitrary optimiser hints merely to force a join
algorithm.

## 0.30.2 - SEMI JOIN

Implement existence-based filtering:

``` sql
SELECT v.*
FROM @channel OF videos AS v
SEMI JOIN @playlist AS p
    ON v.id = p.id
```

Return only left-side rows with at least one right-side match. The right
relation contributes no projected columns merely by participating.

For stable equality keys, prefer acquiring only right-side key fields,
constructing a membership structure, filtering the left side early, and
deferring deeper left-side metadata where semantics permit.

Cover duplicate and NULL keys, composite keys, heterogeneous sources,
CTEs, set expressions, ordering, limits, aggregates, windows and
optimiser differential behaviour.

## 0.30.3 - ANTI JOIN

Implement first-class exclusion:

``` sql
SELECT v.*
FROM @channel OF videos AS v
ANTI JOIN @playlist AS p
    ON v.id = p.id
```

Use this as the canonical operation for channel videos not in a
playlist, media absent from another archive/source list, uploads absent
from another facet, and similar exclusion queries.

Define semantics directly rather than rewriting to `NOT IN`, avoiding
its NULL traps.

Prefer plans that acquire only right-side keys, materialise compact
membership state, enumerate the left side incrementally where safe,
reject matches before expensive metadata acquisition, and retain
provenance for survivors.

## 0.30.4 - INNER JOIN

Add inner join where fields from both independently acquired relations
are required.

Support equality joins first. Require qualification for ambiguous
fields.

Do not infer media equivalence from titles or fuzzy metadata. Users may
explicitly join on such fields, but Discover must not present them as
stable identities.

Plan materialised versus streamed sides, minimum fields, duplicate
multiplication and metadata depth using rule/capability-based reasoning.

## 0.30.5 - LEFT JOIN

Add left outer join where retaining every row from the primary media
relation is useful.

Define NULL extension precisely.

Document when ANTI JOIN is clearer and potentially cheaper than
`LEFT JOIN ... WHERE right.id IS NULL`.

Recognise that idiom as an anti join only when equivalence is formally
proven under yt-sql NULL semantics.

## 0.30.6 - Composite and non-identity joins

Extend predicates beyond one stable ID where useful, including composite
equality keys and explicit scalar metadata equality.

Review inequality/range joins separately.

Do not introduce fuzzy matching, edit distance, similarity joins or
implicit title normalisation.

Preserve exact yt-sql Unicode comparison semantics.

## 0.30.7 - Join composition

Compose joins with CTEs, UNION/UNION ALL/INTERSECT/EXCEPT, GROUP
BY/HAVING, aggregate FILTER, windows/QUALIFY, DISTINCT, deterministic
row selection, ORDER BY, OFFSET/LIMIT and typed metadata collection
expansion.

Define precedence and canonical formatting unambiguously.

## 0.30.8 - Join-aware field and metadata pruning

Calculate each side's minimum required fields from join keys, local
predicates, projection, later relational operations, provenance and
identity.

A SEMI/ANTI membership relation should not acquire unrelated metadata.

Propagate outer requirements into CTEs and join operands.

## 0.30.9 - Join-aware predicate placement

Determine the earliest safe execution point for WHERE and ON predicates.

Apply side-local filtering, capability-driven branch elimination,
independent temporal/frontier bounds and enumeration-safe filters where
proven valid.

Never move predicates across outer-join boundaries when NULL-extension
semantics would change.

Require optimiser differential coverage for every transformation.

## 0.30.10 - Join acquisition ordering

Introduce deterministic rule-based acquisition planning.

Consider SEMI/ANTI membership-side-first acquisition, key-only sources,
statically bounded sources, source/facet capabilities and valid
cache/frontier state.

Do not fabricate precise costs from unreliable extractor information.

## 0.30.11 - Join execution strategies

Implement only justified strategies:

-   hash/membership lookup for suitable equality SEMI/ANTI joins;
-   hash join for suitable equality INNER/LEFT joins;
-   conservative nested evaluation only for bounded cases where
    necessary.

Internal hash tables do not imply user-visible SQL hashing functions.

Guard against accidental unbounded Cartesian behaviour.

## 0.30.12 - Multi-way joins

Review chained joins after two-relation joins are stable.

Support only if concrete use cases justify the planning complexity.

If implemented, preserve deterministic association/precedence, plan each
source independently, propagate minimum field requirements and prohibit
optimiser reordering unless equivalence is proven.

## 0.30.13 - RIGHT and FULL JOIN review

Evaluate RIGHT JOIN and FULL OUTER JOIN after INNER, LEFT, SEMI and ANTI
joins.

RIGHT JOIN may add little beyond inversion of LEFT JOIN.

FULL OUTER JOIN has relation-comparison uses but greater schema,
NULL-extension and materialisation complexity.

This phase may conclude that either remains unsupported.

## 0.30.14 - Cartesian-product review

Keep CROSS JOIN and implicit Cartesian products unsupported by default.

Implement only if a bounded Discover-native use case genuinely requires
them.

SQL familiarity alone is insufficient justification.

## 0.30.15 - yt-dlp translation and extractor cooperation

Review every supported join form for work that can be translated or
reduced before local composition.

Potential strategies include flat/enumeration metadata for identity-only
operands, independently translated temporal/source filters,
capability-driven impossible-branch elimination, deeper acquisition only
for surviving candidates, and independent reuse of valid cache/frontier
information.

Do not claim yt-dlp performs the join unless it genuinely does. Discover
performs irreducible relational composition locally.

## 0.30.16 - Explain and diagnostics

Expose logical join type, operands, source/facet identities, join keys,
required fields per side, pre-acquisition filters, metadata levels,
materialised/streamed sides, execution strategy, eliminated operands and
rejected optimisation reasons.

Provide deterministic errors for ambiguous fields, unknown aliases,
incompatible key types, unsupported predicates/forms and accidental
Cartesian queries.

## 0.30.17 - Join torture suite

Cover zero/one-row relations, duplicate keys, all common cardinalities,
NULL and incompatible keys, Unicode/temporal keys,
dynamic/unavailable/unacquired fields, heterogeneous extractors, same
source with different facets, CTE/set operands, nested collections,
aggregates/windows, volatility, deterministic errors and
optimised/unoptimised equivalence.

Keep broad scale stress outside routine CI.

## 0.30.18 - Relational reconciliation

Reconcile `YT-SQL.md`, `YT-SQL-OPTIMISATION.md`,
`YT-SQL-TEST-COVERAGE.md`, `DISCOVER-README.md`, help/examples,
deterministic dataset generator, conformance fixtures, parser torture
corpus, TODO and roadmap status.

Remove obsolete blanket statements that JOIN is inherently out of scope.
Replace them with the narrower principle that relational composition is
supported only where it provides concrete Discover value and preserves
acquisition-aware semantics.

Record deliberately rejected/deferred forms.

## Deferred beyond 0.30.x unless separately justified

-   Fuzzy or similarity joins.
-   Implicit title matching.
-   Arbitrary Cartesian products.
-   Database statistics catalogues.
-   User-controlled join-algorithm hints.
-   Generic cost-based optimisation based on invented extractor costs.
-   Distributed join execution.
-   Persistence/index infrastructure merely to accelerate joins.
-   JOIN support as a route to DML, DDL or general database emulation.

## Roadmap maintenance

This file is a living programme document. Mark each sub-phase complete
as it lands and reconcile speculative wording with durable implemented
behaviour. Remove duplicated TODO material and obsolete transitional
wording during series reconciliation.

The canonical location for programme documents is `docs/roadmap/`.

During active 0.30.x development, structural cleanup may wait until the
series closes.
