# yt-discover 0.28.x - Owsome Optimisations

## Purpose

The 0.28.x series builds an optimiser for Discover's actual problem: querying remote, heterogeneous media metadata through yt-dlp and extractor-specific capabilities. Local expression simplification matters, but avoiding unnecessary enumeration and metadata acquisition matters more.

The optimiser must never assume that Discover is a conventional database. It must preserve yt-sql's three-valued NULL semantics, temporal types, Unicode rules, volatility, source/facet identity and deterministic output while translating as much safe work as possible into acquisition constraints that yt-dlp or an extractor adapter can understand.

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

Introduce a formal property-analysis pass over resolved expressions, relations and query stages.

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
-   structurally unavailable field whose logical value is necessarily NULL;
-   logically supported field not yet acquired.

The last state must never be converted into SQL NULL by optimiser reasoning.

### Testing

Property results should be deterministic and testable independently of execution.

### Implemented

`query_properties.py` now provides deterministic expression and query property analysis without performing acquisition. The framework records resolved type, required fields, constantness, deterministic or volatile behaviour, NULL sensitivity, grouping dependence, earliest safe evaluation stage, metadata depth, source/facet dependencies, ordering requirements, cardinality effects and whether complete relation acquisition is required.

The internal knowledge-state model keeps acquired scalar values, acquired SQL NULL, structurally unavailable fields and supported-but-not-yet-acquired metadata distinct. In particular, metadata that has not been acquired is not interpreted as SQL NULL. Seeded `RANDOM(seed)` is recorded as deterministic but row-dependent, while unseeded `RANDOM()` remains volatile.

## 0.28.1 - Optimiser Proof and Safety Framework - Complete

### Scope

Replace or wrap ad hoc rewrites with reusable proofs where practical.

A transformation should be able to state which semantic facts justify it, for example:

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

### Implementation

0.28.1 introduces a reusable proof layer with explicit proven and not-proven states, proof provenance and deterministic reasons. Constant folding and duplicate predicate elimination consume these proofs, and optimiser decisions retain them for later explain/diagnostic rendering. Syntactic equality alone is not sufficient to eliminate a volatile expression. Structural field unavailability is proven only from source/facet capability declarations; unknown or unacquired metadata remains unproven.

## 0.28.2 - Capability-Driven Predicate Simplification - Complete

### Scope

Use source/facet capability information during semantic optimisation.

If `duration` is structurally unavailable and therefore SQL NULL for every row in a branch:

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
-   aggregate/HAVING expressions where the relation is already known empty or constant.

### Branch-aware behaviour

A predicate may eliminate one UNION branch while leaving another intact if their capabilities differ.

### yt-dlp translation

When branch elimination is proven, do not invoke yt-dlp for that physical branch at all.

### Implementation

0.28.2 adds source/facet-aware predicate truth proofs that distinguish a proven SQL UNKNOWN result from an optimiser refusal. Direct comparisons, BETWEEN, IN and text predicates over structurally unavailable fields are proven UNKNOWN, while IS NULL and IS NOT NULL are proven TRUE or FALSE as appropriate. Boolean AND, OR and NOT compose these results using SQL three-valued logic, including dominating FALSE for AND and TRUE for OR.

The resolved optimiser may replace a capability-proven predicate with an explicit TRUE, FALSE or NULL predicate literal and retains the proof in its decision record. The physical planner independently marks a source branch as empty when the complete WHERE predicate is proven unable to evaluate TRUE. Such a branch receives a `skip` acquisition mode, zero network cost and an attached elimination proof. Ordinary and dynamic metadata remain unchanged unless a stable source/facet capability declaration supplies the proof.

Single-source application acquisition honours the `skip` mode before invoking yt-dlp. Multi-source source-boundary planning remains conservative until the dedicated branch-planning work later in this series.

## 0.28.3 - Field Requirement and Metadata Pruning - Complete

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

Where yt-dlp supports flat/lazy enumeration, extractor arguments, metadata-skipping options, format-skipping options or equivalentcontrols, adapters should request no more information than the physical plan requires.

Translation must be capability-based and tested. It must not depend on undocumented assumptions that can silently change results.

### Implemented

0.28.3 partitions the complete physical field requirement into exact enumeration fields and fields that still require detailed metadata. Approximate flat values remain detailed requirements for authoritative query evaluation, and dynamic fields remain conservative detailed requirements.

The physical acquisition request exposes both partitions together with the predicate-specific enumeration and detailed requirements. Eligible single-source queries whose fields are all exact in lightweight enumeration can therefore avoid detailed yt-dlp extraction entirely. Mixed queries may evaluate exact flat predicate information before detailed extraction, then overlay those exact flat values onto cached or freshly detailed rows. This allows cache freshness to cover only the genuinely detailed fields without allowing stale cached enumeration values to influence query semantics.

Enumeration-only full-source execution does not use an incremental cache frontier, because doing so could combine freshly enumerated rows with older cached values for exact enumeration fields. It performs a complete lightweight enumeration instead.

## 0.28.4 - Staged Predicate Evaluation - Complete

### Scope

Partition predicates according to the earliest metadata stage at which they can be safely evaluated.

Example stages may include:

-   source identity/facet;
-   enumeration metadata;
-   lightweight entry metadata;
-   full entry metadata;
-   format/collection metadata.

Rows may be rejected before deeper acquisition only when existing information proves that the final predicate cannot evaluate to TRUE.

### Partial knowledge

A missing value because it has not yet been acquired is an internal planning state, not SQL NULL.

### yt-dlp translation

Where yt-dlp can reject entries or limit deeper extraction using filters that exactly match yt-sql semantics, translate eligible predicate fragments. Otherwise perform staged local filtering between acquisition levels.

Never translate a predicate whose yt-dlp interpretation differs in NULL, date, string, regex or numeric semantics.

### Implementation

0.28.4 introduces an explicit predicate-stage plan. Safe top-level `AND` terms whose complete dependencies are deterministic and authoritative at enumeration time are separated from residual terms that require later metadata. Mixed `OR` and `NOT` expressions remain intact unless the complete expression is safe at enumeration time.

Enumeration-stage execution rejects a candidate only when all required exact values for a staged term have actually been acquired and that term cannot evaluate TRUE. Missing dictionary fields remain not-acquired knowledge rather than becoming SQL NULL, while an explicitly acquired NULL retains normal three-valued WHERE semantics. Existing conservative proofs from approximate lightweight metadata remain available as an independent one-sided rejection path and are not promoted to authoritative evaluation.

Human-readable and JSON explain output expose the enumeration and residual predicate fragments, their field dependencies and the reason for the selected stage split.

## 0.28.5 - Temporal Bound and Frontier Inference - Complete

### Scope

Infer safe acquisition constraints from temporal predicates such as:

``` sql
upload_date >= ...
upload_date < ...
release_timestamp BETWEEN ... AND ...
```

### Capability requirement

Only use an acquisition frontier when the relevant source/facet adapter declares a trustworthy ordering or suitable yt-dlp filtering capability.

### Possible translations

Where an extractor supports stable date-range options or equivalent yt-dlp controls, translate proven bounds into those controls. Where it does not, use ordered early termination only when the adapter's ordering capability proves it safe.

### Interaction with cache/frontier state

Inferred query bounds and persisted acquisition frontiers must compose conservatively. A query-specific optimisation must never corrupt or overstate the reusable cache frontier.

### Implementation

0.28.5 introduces a typed temporal-bound plan for `upload_date`, `date`, `timestamp`, `release_timestamp` and `modified_timestamp`. Comparisons, non-negated `BETWEEN`, non-negated `IN`, `AND` and `OR` are analysed conservatively. `AND` retains the strongest compatible bounds, while `OR` retains only a weaker bound implied by every branch. `NOT`, negated range/membership predicates and unparseable temporal literals do not produce acquisition bounds.

A proven lower `upload_date` or `date` bound becomes an ordered acquisition frontier only for channel video sources whose capability contract already permits the existing newest-first bounded scan. Strict date lower bounds advance the frontier by one day. Timestamp bounds and upper date bounds remain planner information until a backend capability can represent them with equivalent semantics.

Query-specific bounded scans continue to be recorded only as observations and never establish complete source ordering, detailed coverage or a reusable cache frontier. Human-readable, JSON and verbose diagnostics expose the inferred interval independently from whether a physical acquisition frontier can use it.

## 0.28.6 - Source-Boundary Predicate and Requirement Planning - Complete

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

Do not push requirements across heterogeneous branches unless their semantics and schemas make that transformation provably equivalent.

### Implementation

0.28.6 introduces an explicit source-boundary plan for each unique `(physical source, logical facet)` request. Each boundary owns its required fields, staged pre-acquisition predicate, metadata requirements, temporal bounds, stable ordering declaration, acquisition strategy, cost classification, collection requirements and branch-emptiness proof. Logical UNION and CTE evaluation remain unchanged above this physical planning layer.

When the same source/facet is used by more than one logical branch, physical field requirements are unioned and the pre-acquisition predicate is the OR of the branch predicates. This retains any row that could be needed by at least one use. If any reuse is unfiltered, no physical pre-acquisition predicate is inferred. Different facets of the same source remain separate boundaries and are never merged merely because their underlying channel identity matches.

Capability-proven empty boundaries may be skipped before multi-source acquisition. Other per-boundary acquisition strategies are exposed by the planner but execution remains conservative where branch-local lowering would require additional orchestration. Outer CTE consumer requirements are not propagated into CTE producers in this phase; that belongs to 0.28.7.

## 0.28.7 - CTE Dependency Propagation - Complete

### Scope

Propagate outer field requirements backwards into non-recursive CTE producers.

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

may require only `id` and `duration` from the physical source if no other semantic requirement depends on the discarded fields.

### Volatility

Do not duplicate, remove or reorder volatile expressions such as unseeded RANDOM in ways that change evaluation count or observable value.

### Materialisation semantics

Document enough CTE execution semantics to make every propagation transformation auditable.

### Implementation

0.28.7 introduces a backwards CTE dependency plan without rewriting the logical query tree. Downstream references seed each CTE's required exported columns, then requirements propagate in reverse declaration order through earlier non-recursive CTEs. A physical producer therefore acquires metadata only for exported expressions that remain observable downstream plus fields required by the producer's own filtering, grouping and ordering semantics.

Unused deterministic projections may stop contributing metadata requirements. Volatile projections remain retained even when no downstream consumer references them, preserving the existing declaration-order CTE materialisation model and volatile evaluation count. `DISTINCT` is a pruning barrier because projected columns participate in row identity, and set-composed CTE producers remain conservative because positional UNION reconciliation requires a separate branch-wise proof.

The query AST and materialised CTE schema are not rewritten in this phase. Dependency propagation affects physical metadata requirements only, so aliases, output order and logical CTE semantics remain unchanged. Human-readable and JSON explain output expose required outputs, retained outputs, pruned outputs, physical input fields and the reason a CTE was or was not pruned.

Explain output distinguishes pre-propagation logical requirements from the post-propagation physical metadata plan. Acquisition strategy, detailed-metadata status and estimated cost are presented from the final physical source boundary so fields proven unnecessary by CTE propagation are not simultaneously described as active acquisition requirements.

## 0.28.8 - Safe LIMIT/OFFSET Early Termination - Complete

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

Where yt-dlp exposes playlist/end/range controls that exactly represent the proven acquisition bound, use them. Otherwise stop local iteration once enough final rows are proven.

The planner must not confuse "request N entries" with "need N final rows" when filters can remove rows.

### Implementation

0.28.8 formalises LIMIT/OFFSET termination as a stage-aware proof. The planner records `OFFSET + LIMIT` as the authoritative match target and distinguishes lightweight-enumeration termination from detailed-metadata termination.

Explicit ordering, DISTINCT, aggregation/HAVING, CTE materialisation, UNION composition, dynamic fields and volatile expressions remain proof barriers. When the complete predicate and projection are authoritative in lightweight metadata, lazy enumeration may stop after enough emitted matching rows. Otherwise source enumeration remains exhaustive and only detailed acquisition may stop early.

yt-dlp positional item ranges are not used as final-row limits because skipped or unavailable source positions need not correspond to emitted query rows. Explain, explain-analyse and run reports expose the selected termination mode.

## 0.28.9 - Static Relation and Branch Simplification - Complete

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

### Implementation

0.28.9 adds a proof-backed relation simplification layer beneath scalar predicate rewriting. It reasons about whether a WHERE or HAVING filter can ever evaluate TRUE, which is the relevant relational question under SQL three-valued logic. A predicate may therefore prove a relation empty even when its scalar value would be UNKNOWN for NULL rows.

The planner detects incompatible same-field equality and range constraints, mutually exclusive NULL requirements, constant HAVING predicates, and source-capability predicates that are provably TRUE, FALSE or UNKNOWN. Proven TRUE WHERE filters are removed from physical predicate work, and proven TRUE HAVING filters are omitted from physical grouping requirements. Proven FALSE or UNKNOWN filters make the affected logical use empty before acquisition.

Source-boundary planning excludes empty logical uses from field unions and combined physical predicates. If every logical use of a source/facet is empty, the complete physical boundary is skipped. In UNION and UNION ALL plans, an empty branch may therefore avoid acquisition independently while live branches retain their normal semantics. Empty uses of a shared source also stop contributing metadata requirements without changing the logical query tree.

The relation simplifier does not rewrite the user-visible AST into a synthetic empty-relation syntax. Logical evaluation remains unchanged; the new proofs affect physical planning, acquisition and diagnostics. Existing scalar optimiser rules for duplicate predicates, exact membership/bound subsumption and double negation remain responsible for expression-level simplification.

Human and JSON explain output report eliminated logical uses, redundant WHERE filters and the proof reason for each static relation simplification.

## 0.28.10 - Metadata Acquisition Plan - Complete

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

Not every adapter must support every stage. The plan expresses requirements; adapters report which distinctions they can honour.

The physical plan should be backend-neutral rather than modelled directly as yt-dlp command-line arguments. Capability-based lowering may target yt-dlp, youtube-dl, gallery-dl, indexed or API-backed sources, and other useful adapters. Unsupported operations remain in the local evaluator unless an adapter can implement them with equivalent semantics. Mixed-backend plans must preserve source/facet identity, provenance, cache isolation and deterministic explainability.

### yt-dlp integration

Map each physical stage to supported yt-dlp invocation choices, extractor arguments or post-enumeration fetches. Keep the mapping isolated in adapters so query semantics do not become tied to command-line syntax used by a particular yt-dlp release.

### Implementation

0.28.10 introduces a backend-neutral `PhysicalAcquisitionPlan` for every physical source/facet boundary. The plan contains ordered semantic stages for source identity enumeration, basic authoritative metadata, complete entry metadata, formats, subtitles and automatic captions, chapters, thumbnails, tags, and open-ended `raw.*` metadata.

The stage plan is derived from the already-pruned physical field requirements rather than from the original logical query. It therefore composes with capability simplification, CTE dependency propagation, source-boundary pruning, static relation elimination and empty-branch removal. A source boundary proven empty has no required acquisition stages.

The current yt-dlp lowering is isolated in the yt-dlp adapter layer. Identity and basic metadata stages map to flat enumeration where that execution path is available. Complete metadata and collection-specific stages map to complete JSON extraction because yt-dlp does not currently expose those semantic collections as independently acquirable stages in Discover's execution model. The logical plan retains the distinction so a future backend can honour a finer-grained capability without changing yt-sql semantics.

Runtime detailed-metadata decisions now consume the explicit physical acquisition plan rather than re-deriving that requirement from incidental control flow. Verbose output reports the selected metadata stages, and human and JSON explain output expose every stage, its fields, whether it is required, and how the current yt-dlp lowering collapses stages.

The plan remains a requirements model, not a promise that every backend can fetch each stage separately. Unsupported or collapsed distinctions are reported by lowering rather than erased from the planner representation.

## 0.28.11 - Cost and Selectivity Heuristics - Complete

### Scope

Add conservative heuristics only where exact semantic equivalence is already guaranteed.

Potential uses:

-   schedule acquisitions by expected information value per acquisition cost, rather than by a simple cheapest-first rule;
-   run a moderately costly high-selectivity or high-elimination branch before cheaper work when it can avoid substantially more expensive dependent acquisition;
-   choose which independently evaluable cheap predicate terms to evaluate first locally;
-   choose whether a deeper metadata stage is worthwhile before another local test;
-   order source-branch acquisition where final semantics do not depend on branch acquisition order;
-   avoid acquiring expensive collections until a row survives cheaper filters.

An explicit opt-in bounded-concurrency mode may later execute independent acquisitions in parallel under an orchestrator. Any such design must preserve deterministic consolidation, provenance and cache isolation, resource limits, cancellation, partial-failure handling and safe early termination.

### Non-goal

Do not invent precise cost estimates that the extractor cannot justify. Prefer coarse capability tiers and measured deterministic rules over false numerical precision.

### Implementation

0.28.11 adds deterministic coarse cost, selectivity and information-value heuristics on top of the explicit physical acquisition plan. The heuristics use named tiers rather than fabricated numeric probabilities or timings.

Safe enumeration-stage top-level AND terms are ranked by expected information value per local evaluation cost. Equality and small positive membership predicates receive stronger selectivity guidance than broad inequalities, negated predicates and otherwise unclassified forms. Expensive local text matching remains less attractive than equally selective cheap comparisons. Ties retain original query order. Only deterministic terms already proven safe for independent enumeration-stage evaluation are eligible for reordering, so the logical query AST and residual evaluation order remain unchanged.

Physical source/facet boundaries record a coarse acquisition cost tier, the strongest available enumeration selectivity tier, the corresponding information-value tier and any expensive metadata stages that can remain deferred until cheap enumeration filters have survived. The acquisition cost tier is aligned with the existing planner cost class so explain output does not present contradictory cost labels.

The runtime already evaluates authoritative enumeration predicates before detailed extraction where that staged path exists. 0.28.11 makes the cheap-term order heuristic explicit and observable rather than adding speculative backend behaviour. Nested collection and dynamic/raw metadata stages are identified as expensive deferred work when cheap authoritative filters are available, even when the current yt-dlp lowering ultimately collapses those stages into complete JSON extraction.

Source-branch acquisition order is not changed in this release. Although the planner can describe independent source boundaries, there is not yet a proven cross-branch bailout or dependency rule that would make cost-based branch reordering reduce required work. Bounded concurrent acquisition also remains future work.

Human and JSON explain output expose predicate selectivity, local evaluation cost, information value, whether the safe enumeration order changed, boundary cost/selectivity tiers and deferred expensive stages.

## 0.28.12 - Explainable Optimisation and Acquisition - Complete

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

Keep explain structures versionable and deterministic so later machine interfaces do not need to scrape human prose.

Human-readable diagnostics may additionally render deterministic Unicode query-plan and decision-tree graphs from the actual planner representation, with a plain-ASCII fallback for logs, CI and terminals where box drawing is unsuitable. Graphs may expose logical structure, optimiser decisions, backend selection, acquisition dependencies, information-value and cost estimates, pushdown versus residual evaluation, concurrency groups, bailout conditions and result consolidation. This phase settles the initial presentation controls and rendered SVG interface while leaving any broader future renderer UX open to evidence.

### Implementation

0.28.12 introduces a versioned presentation-level explanation model derived from the existing machine explain payload. The model records deterministic planner decisions and graph structure without moving query semantics into a renderer.

Console explain output gains a compact plan overview and planner-decision tree before the detailed semantic explanation. Applied, rejected, deferred and eliminated decisions are labelled in words rather than pictographic status symbols. Rich terminal mode uses conservative ANSI colour plus dependable Unicode box drawing and arrows. `--colour auto|always|never` and `--unicode auto|always|never` provide explicit control; automatic mode disables ANSI colour and Unicode structure for redirected output, respects `NO_COLOR`, and falls back to ASCII when the stream encoding cannot represent the selected Unicode set.

The machine JSON representation remains presentation-neutral and now carries an explicit explanation schema version together with the deterministic decision list and graph model. ANSI escape sequences are never introduced into JSON.

Rendered explain output uses Graphviz as an optional presentation dependency and emits SVG from the same explanation graph used by the console view. Graphviz availability therefore affects only rendered presentation, not parsing, optimisation, planning or query execution. No separate HTML/web renderer is introduced in this phase.

The decision model exposes safe predicate staging, source-boundary predicate pushdown, acquisition strategy selection or rejection, deferred expensive metadata stages, branch elimination, CTE projection pruning and LIMIT-aware termination where those decisions are present. Existing detailed explain sections continue to expose field requirements, capability availability, acquisition stages, yt-dlp lowering, temporal bounds and heuristic guidance.

## 0.28.13 - Optimiser Differential and Acquisition Torture

### Scope

Reconcile the full optimiser against the accepted semantic corpus.

Require optimised and deliberately unoptimised execution to produce identical observable results for deterministic cases.

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

Use property-based tests, generated query transformations and mutation testing where they expose classes of optimiser mistakes that ordinary fixtures may miss.

### Implementation

0.28.13 reconciles the complete 0.28 optimiser programme against a broader deterministic differential corpus. Each deterministic case executes both the original resolved query and the optimised query and requires identical observable rows, then optimises the result a second time and requires a stable query with no further optimiser decisions.

The corpus spans SQL NULL and three-valued logic, Unicode, temporal infinity and relative dates, decimal and alternate-base numeric forms, CASE and scalar functions, aggregate FILTER, GROUP BY/HAVING, CTE chains, UNION and UNION ALL, heterogeneous source schemas, same-source cross-facet identity, DISTINCT, LIMIT/OFFSET and seeded RANDOM. Canonical format/parse round-trips and repeated malformed-input failures are checked alongside execution equivalence. Volatile `RANDOM()` remains an execution-time expression and is not subjected to result-equality assertions that would mistake volatility for an optimiser difference.

Generated equivalent Boolean transformations exercise duplicate predicates and double negation over several predicate families. A small deterministic mutation-style sensitivity matrix proves that the fixture corpus can detect representative unsafe changes to comparison boundaries, equality polarity, AND/OR composition and NULL predicates. These checks provide useful mutation-style confidence without adding a heavyweight mutation runner to routine CI. External property-based and full mutation-testing tools remain available for explicit future hardening where their additional cost is justified.

Physical-planning torture coverage composes the optimiser with acquisition decisions. It checks static empty-branch elimination, LIMIT termination barriers, detailed-stage stopping, temporal frontiers, deferred expensive metadata, cross-facet source identity, CTE requirement pruning, reused-source union requirements, dynamic raw metadata and volatile random ordering. The tests also retain the semantic distinction between structurally unavailable metadata and metadata that has merely not yet been acquired.

No new optimiser rewrite is introduced by this phase. The purpose is to prove the accumulated 0.28 optimisation and acquisition behaviour against the accepted language semantics and to expose regressions before the optimisation series is closed.

## Roadmap maintenance

This file is a living programme document. As each sub-phase is completed, mark it complete and reconcile the description with durable implemented behaviour. Keep transient local-acceptance notes out of committed product documentation. During an active version series, structural cleanup may be deferred until the series closes, at which point stale notes, duplicated TODOs and obsolete transitional wording should be removed.

The canonical location for these programme documents is `docs/roadmap/`.

### Runtime Boolean short-circuiting

A later optimiser/execution pass should evaluate Boolean chains with SQL three-valued short-circuit semantics. `AND` may stop as soon as an operand is FALSE, while `OR` may stop as soon as an operand is TRUE. UNKNOWN must retain exact SQL three-valued behaviour. Equivalent safe behaviour should apply to HAVING where relevant. Predicate reordering is a separate optimisation and requires explicit volatility and semantic safety proofs.
