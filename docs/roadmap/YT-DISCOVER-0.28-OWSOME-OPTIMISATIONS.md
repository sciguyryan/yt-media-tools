# yt-discover 0.28.x - Owsome Optimisations

## Purpose

The 0.28.x series builds an optimiser for Discover's actual problem:
querying remote, heterogeneous media metadata through yt-dlp and
extractor-specific capabilities. Local expression simplification
matters, but avoiding unnecessary enumeration and metadata acquisition
matters more.

The optimiser must never assume that Discover is a conventional
database. It must preserve yt-sql's three-valued NULL semantics,
temporal types, Unicode rules, volatility, source/facet identity and
deterministic output while translating as much safe work as possible
into acquisition constraints that yt-dlp or an extractor adapter can
understand.

The spelling of "Owsome" is normative.

## Optimisation priority

Prefer optimisations in this order:

1.  avoid an entire source/facet acquisition;
2.  avoid unnecessary entries;
3.  avoid unnecessary per-entry metadata acquisition;
4.  terminate acquisition safely as soon as the final result is proven;
5.  reduce local relation work;
6.  reduce scalar expression work.

## 0.28.0 - Semantic Property Framework - Complete

### Scope

Introduce a formal property-analysis pass over resolved expressions,
relations and query stages.

Track properties including:

-   required logical fields;
-   source/facet dependencies;
-   resolved type;
-   constantness;
-   deterministic versus volatile behaviour;
-   NULL sensitivity;
-   cardinality effects;
-   ordering requirements;
-   grouping/window dependence;
-   earliest safe evaluation stage;
-   metadata depth required;
-   whether an expression can be decided from enumeration metadata;
-   whether a relation requires complete acquisition.

### Knowledge-state model

Explicitly distinguish at least:

-   known scalar value;
-   SQL NULL;
-   structurally unavailable field whose logical value is necessarily
    NULL;
-   logically supported field not yet acquired.

The last state must never be converted into SQL NULL by optimiser
reasoning.

### Testing

Property results should be deterministic and testable independently of
execution.

### Implemented

`query_properties.py` now provides deterministic expression and query
property analysis without performing acquisition. The framework records
resolved type, required fields, constantness, deterministic or volatile
behaviour, NULL sensitivity, grouping dependence, earliest safe evaluation
stage, metadata depth, source/facet dependencies, ordering requirements,
cardinality effects and whether complete relation acquisition is required.

The internal knowledge-state model keeps acquired scalar values, acquired SQL
NULL, structurally unavailable fields and supported-but-not-yet-acquired
metadata distinct. In particular, metadata that has not been acquired is not
interpreted as SQL NULL. Seeded `RANDOM(seed)` is recorded as deterministic but
row-dependent, while unseeded `RANDOM()` remains volatile.

## 0.28.1 - Optimiser Proof and Safety Framework

### Scope

Replace or wrap ad hoc rewrites with reusable proofs where practical.

A transformation should be able to state which semantic facts justify
it, for example:

-   expression is deterministic;
-   expression contains no volatile descendants;
-   field is guaranteed NULL for this source/facet;
-   ordering is preserved;
-   relation cardinality cannot increase;
-   query result does not depend on discarded fields.

### Safety invariants

Never violate:

-   SQL-like three-valued logic;
-   seeded and volatile RANDOM distinction;
-   query-captured temporal semantics;
-   typed temporal infinity;
-   exact Unicode semantics;
-   deterministic output and ties;
-   source/facet identity;
-   CTE scope/materialisation behaviour;
-   set-operation semantics.

## 0.28.2 - Capability-Driven Predicate Simplification

### Scope

Use source/facet capability information during semantic optimisation.

If `duration` is structurally unavailable and therefore SQL NULL for
every row in a branch:

``` sql
WHERE duration >= 1d
```

can never be TRUE, so the branch may be eliminated before acquisition.

Support safe reasoning for:

-   comparisons;
-   BETWEEN;
-   IN;
-   IS NULL / IS NOT NULL;
-   LIKE / ILIKE;
-   CONTAINS / MATCHES where their NULL contract permits;
-   Boolean combinations;
-   aggregate/HAVING expressions where the relation is already known
    empty or constant.

### Branch-aware behaviour

A predicate may eliminate one UNION branch while leaving another intact
if their capabilities differ.

### yt-dlp translation

When branch elimination is proven, do not invoke yt-dlp for that
physical branch at all.

## 0.28.3 - Field Requirement and Metadata Pruning

### Scope

Compute the complete minimal logical field set required by a query.

Requirements may originate from:

-   SELECT projection;
-   WHERE;
-   GROUP BY;
-   aggregate arguments;
-   aggregate FILTER;
-   HAVING;
-   DISTINCT;
-   ORDER BY;
-   OFFSET/LIMIT planning;
-   CTE consumers;
-   set schema reconciliation;
-   output/provenance requirements;
-   hidden semantic requirements such as stable identity.

### Acquisition translation

Where yt-dlp supports flat/lazy enumeration, extractor arguments,
metadata-skipping options, format-skipping options or equivalent
controls, adapters should request no more information than the physical
plan requires.

Translation must be capability-based and tested. It must not depend on
undocumented assumptions that can silently change results.

## 0.28.4 - Staged Predicate Evaluation

### Scope

Partition predicates according to the earliest metadata stage at which
they can be safely evaluated.

Example stages may include:

-   source identity/facet;
-   enumeration metadata;
-   lightweight entry metadata;
-   full entry metadata;
-   format/collection metadata.

Rows may be rejected before deeper acquisition only when existing
information proves that the final predicate cannot evaluate to TRUE.

### Partial knowledge

A missing value because it has not yet been acquired is an internal
planning state, not SQL NULL.

### yt-dlp translation

Where yt-dlp can reject entries or limit deeper extraction using filters
that exactly match yt-sql semantics, translate eligible predicate
fragments. Otherwise perform staged local filtering between acquisition
levels.

Never translate a predicate whose yt-dlp interpretation differs in NULL,
date, string, regex or numeric semantics.

## 0.28.5 - Temporal Bound and Frontier Inference

### Scope

Infer safe acquisition constraints from temporal predicates such as:

``` sql
upload_date >= ...
upload_date < ...
release_timestamp BETWEEN ... AND ...
```

### Capability requirement

Only use an acquisition frontier when the relevant source/facet adapter
declares a trustworthy ordering or suitable yt-dlp filtering capability.

### Possible translations

Where an extractor supports stable date-range options or equivalent
yt-dlp controls, translate proven bounds into those controls. Where it
does not, use ordered early termination only when the adapter's ordering
capability proves it safe.

### Interaction with cache/frontier state

Inferred query bounds and persisted acquisition frontiers must compose
conservatively. A query-specific optimisation must never corrupt or
overstate the reusable cache frontier.

## 0.28.6 - Source-Boundary Predicate and Requirement Planning

### Scope

Build a physical request independently for every source/facet branch.

Each branch should determine:

-   required fields;
-   pre-acquisition predicates;
-   temporal bounds;
-   metadata depth;
-   stable ordering assumptions;
-   early-termination opportunity;
-   branch emptiness;
-   collection/format requirements.

### Composition

Do not push requirements across heterogeneous branches unless their
semantics and schemas make that transformation provably equivalent.

## 0.28.7 - CTE Dependency Propagation

### Scope

Propagate outer field requirements backwards into non-recursive CTE
producers.

Example:

``` sql
WITH candidates AS (
    SELECT id, title, duration, view_count
    FROM @foo
)
SELECT id
FROM candidates
WHERE duration < 10m
```

may require only `id` and `duration` from the physical source if no
other semantic requirement depends on the discarded fields.

### Volatility

Do not duplicate, remove or reorder volatile expressions such as
unseeded RANDOM in ways that change evaluation count or observable
value.

### Materialisation semantics

Document enough CTE execution semantics to make every propagation
transformation auditable.

## 0.28.8 - Safe LIMIT/OFFSET Early Termination

### Scope

Formalise when acquisition may stop before the source is exhausted.

The proof must account for:

-   source order;
-   final ORDER BY;
-   WHERE selectivity and evaluation stage;
-   OFFSET;
-   LIMIT;
-   DISTINCT;
-   aggregation/HAVING;
-   CTEs;
-   UNION/UNION ALL;
-   RANDOM/volatility;
-   later window/QUALIFY semantics once 0.29.x exists.

### yt-dlp translation

Where yt-dlp exposes playlist/end/range controls that exactly represent
the proven acquisition bound, use them. Otherwise stop local iteration
once enough final rows are proven.

The planner must not confuse "request N entries" with "need N final
rows" when filters can remove rows.

## 0.28.9 - Static Relation and Branch Simplification

### Scope

Generalise constant reasoning beyond scalar expressions.

Optimisations may include:

-   statically false WHERE;
-   statically false HAVING;
-   statically true predicates removed from a filter stage;
-   provably empty set branches;
-   redundant exact conditions;
-   safe double-negation and Boolean simplifications;
-   impossible field-capability combinations.

All transformations must preserve NULL semantics.

## 0.28.10 - Metadata Acquisition Plan

### Scope

Represent acquisition explicitly rather than as incidental control flow.

A physical plan should be able to describe stages such as:

-   enumerate source identities;
-   obtain basic entry metadata;
-   obtain complete entry metadata;
-   obtain formats;
-   obtain subtitles/captions;
-   obtain chapters;
-   obtain thumbnails;
-   obtain dynamic/raw fields.

Not every adapter must support every stage. The plan expresses
requirements; adapters report which distinctions they can honour.

The physical plan should be backend-neutral rather than modelled directly as
yt-dlp command-line arguments. Capability-based lowering may target yt-dlp,
youtube-dl, gallery-dl, indexed or API-backed sources, and other useful
adapters. Unsupported operations remain in the local evaluator unless an
adapter can implement them with equivalent semantics. Mixed-backend plans must
preserve source/facet identity, provenance, cache isolation and deterministic
explainability.

### yt-dlp integration

Map each physical stage to supported yt-dlp invocation choices,
extractor arguments or post-enumeration fetches. Keep the mapping
isolated in adapters so query semantics do not become tied to
command-line syntax used by a particular yt-dlp release.

## 0.28.11 - Cost and Selectivity Heuristics

### Scope

Add conservative heuristics only where exact semantic equivalence is
already guaranteed.

Potential uses:

-   schedule acquisitions by expected information value per acquisition cost,
    rather than by a simple cheapest-first rule;
-   run a moderately costly high-selectivity or high-elimination branch before
    cheaper work when it can avoid substantially more expensive dependent
    acquisition;
-   choose which independently evaluable cheap predicate terms to
    evaluate first locally;
-   choose whether a deeper metadata stage is worthwhile before another
    local test;
-   order source-branch acquisition where final semantics do not depend
    on branch acquisition order;
-   avoid acquiring expensive collections until a row survives cheaper
    filters.

An explicit opt-in bounded-concurrency mode may later execute independent
acquisitions in parallel under an orchestrator. Any such design must preserve
deterministic consolidation, provenance and cache isolation, resource limits,
cancellation, partial-failure handling and safe early termination.

### Non-goal

Do not invent precise cost estimates that the extractor cannot justify.
Prefer coarse capability tiers and measured deterministic rules over
false numerical precision.

## 0.28.12 - Explainable Optimisation and Acquisition

### Scope

Extend explain/analyse output to expose meaningful planning decisions.

Include where relevant:

-   required fields;
-   inferred field availability;
-   acquisition stages;
-   predicate staging;
-   source-boundary pushdown;
-   yt-dlp-translatable constraints;
-   temporal frontiers;
-   branch elimination;
-   CTE projection pruning;
-   early-termination proof;
-   optimisation applied;
-   attractive optimisation rejected and why.

### Machine-readable form

Keep explain structures versionable and deterministic so later machine
interfaces do not need to scrape human prose.

Human-readable diagnostics may additionally render deterministic Unicode
query-plan and decision-tree graphs from the actual planner representation,
with a plain-ASCII fallback for logs, CI and terminals where box drawing is
unsuitable. Graphs may expose logical structure, optimiser decisions, backend
selection, acquisition dependencies, information-value and cost estimates,
pushdown versus residual evaluation, concurrency groups, bailout conditions
and result consolidation. Exact CLI spelling remains a later UX decision.

## 0.28.13 - Optimiser Differential and Acquisition Torture

### Scope

Reconcile the full optimiser against the accepted semantic corpus.

Require optimised and deliberately unoptimised execution to produce
identical observable results for deterministic cases.

### Mandatory coverage

-   SQL NULL and three-valued logic;
-   structurally unavailable versus not-yet-acquired metadata;
-   Unicode;
-   temporal literals and infinity;
-   numeric literal forms;
-   CASE and scalar functions;
-   aggregate FILTER;
-   GROUP BY/HAVING;
-   CTEs;
-   UNION/UNION ALL;
-   source/facet identity;
-   heterogeneous schemas;
-   DISTINCT;
-   OFFSET/LIMIT;
-   RANDOM;
-   canonical formatting;
-   malformed input;
-   deterministic error behaviour.

### Additional techniques

Use property-based tests, generated query transformations and mutation
testing where they expose classes of optimiser mistakes that ordinary
fixtures may miss.

## Roadmap maintenance

This file is a living programme document. As each sub-phase is
completed, mark it complete and reconcile the description with durable
implemented behaviour. Keep transient local-acceptance notes out of
committed product documentation. During an active version series,
structural cleanup may be deferred until the series closes, at which
point stale notes, duplicated TODOs and obsolete transitional wording
should be removed.

The canonical location for these programme documents is `docs/roadmap/`.
