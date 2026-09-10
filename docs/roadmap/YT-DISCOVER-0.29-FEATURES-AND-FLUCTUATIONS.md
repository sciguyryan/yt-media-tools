# yt-discover 0.29.x - Features and Fluctuations

## Purpose

The 0.29.x series expands yt-sql after the 0.27.x architectural refactor
and 0.28.x acquisition optimiser are stable. SQL syntax is used where it
gives users a familiar, precise way to query media metadata, but SQL
compatibility is not a goal in itself.

Discover is a metadata query language over heterogeneous yt-dlp
extractors. Its language may therefore add, omit or adapt features
according to media metadata, extractor capabilities, acquisition cost
and the logical source/facet model.

The guiding principle is simple: the more useful query intent Discover
can express and safely translate into work that yt-dlp or an extractor
can perform, the more power the user gains.

## Cross-phase requirements

Every new language feature must include, where applicable:

-   parser coverage;
-   semantic resolution/type coverage;
-   execution coverage;
-   canonical formatting and round-trip coverage;
-   malformed and boundary cases;
-   NULL behaviour;
-   Unicode behaviour;
-   CTE and set-operation composition;
-   optimiser differential coverage;
-   acquisition-planner coverage;
-   explain/diagnostic coverage;
-   deterministic conformance fixtures.

No feature should be added solely because another SQL dialect contains
it.

## 0.29.0 - Comparison and Conversion Syntax

### Statements and operators

Add NULL-safe comparison:

``` sql
a IS DISTINCT FROM b
a IS NOT DISTINCT FROM b
```

These always produce a Boolean and must not collapse ordinary comparison
semantics.

Review and add `IS UNKNOWN` / `IS NOT UNKNOWN` if it materially improves
explicit three-valued-logic queries.

### Conversion

Add:

``` sql
CAST(expr AS type)
TRY_CAST(expr AS type)
```

`CAST` raises a query error for a value-level conversion failure.

`TRY_CAST` returns SQL NULL for a valid conversion whose particular
input cannot be represented. Impossible source/target type combinations
remain semantic errors rather than being silently converted to NULL.

Initial targets should correspond to stable yt-sql logical types,
including integer, real/decimal as supported, text, Boolean, duration,
date and timestamp where conversion semantics are unambiguous.

### Media value

Safe conversion is especially useful for extractor-specific dynamic
fields whose logical representation is known but whose individual values
may be inconsistent.

## 0.29.1 - Set-Operation Statements

### Add

``` sql
INTERSECT
EXCEPT
```

Use existing positional schema reconciliation and logical type
compatibility rules.

### Review separately

-   `INTERSECT ALL`;
-   `EXCEPT ALL`.

Implement multiset variants only if realistic Discover queries benefit
from retaining duplicate multiplicity.

### Optimisation

Allow branch-specific acquisition planning. A branch eliminated by
capability or predicate analysis must not be acquired.

### Non-goal

Do not introduce JOIN to complete a SQL family. Independent source
composition remains set-based.

## 0.29.2 - Ordering and Row Selection Statements

### Add

``` sql
ORDER BY expression NULLS FIRST
ORDER BY expression NULLS LAST
```

Define and document default NULL ordering separately.

### Add

``` sql
LIMIT n WITH TIES
```

Require ORDER BY. Return all rows tied with the final included ordering
key under deterministic comparison semantics.

### Add deterministic DISTINCT ON

``` sql
SELECT DISTINCT ON (expr, ...)
```

Require a deterministic ordering sufficient to select a unique
representative for each distinct key. Reject ambiguous forms rather than
inheriting unpredictable behaviour from dialects that permit it.

### Optimisation impact

These constructs participate directly in safe early-termination proofs.

## 0.29.3 - Window and QUALIFY Statement Architecture

### Add syntax

``` sql
function(...) OVER (...)
```

Window specification initially supports:

``` sql
PARTITION BY ...
ORDER BY ...
ROWS BETWEEN ... AND ...
```

Frame boundaries should include:

-   UNBOUNDED PRECEDING;
-   `n PRECEDING`;
-   CURRENT ROW;
-   `n FOLLOWING`;
-   UNBOUNDED FOLLOWING.

### Add

``` sql
QUALIFY predicate
```

Define a stable yt-sql logical evaluation order. QUALIFY filters after
window evaluation and before final ordering/limiting according to that
contract.

### Deferred window syntax

Evaluate `RANGE`, `GROUPS` and frame `EXCLUDE` only after ROWS semantics
are proven useful and stable.

## 0.29.4 - Temporal Functions

### Add a coherent temporal family

Primary functions:

``` text
EXTRACT
DATE_TRUNC
DATE_DIFF
DATE_ADD
DATE_SUB
```

Supported extraction/truncation units should include useful
media-analysis units such as:

-   year;
-   quarter if useful;
-   month;
-   week where semantics are explicitly defined;
-   day;
-   day of week;
-   hour;
-   minute;
-   second.

### Semantics

Define behaviour for:

-   date;
-   timestamp;
-   duration where applicable;
-   SQL NULL;
-   positive/negative temporal infinity;
-   invalid unit/type combinations.

Preserve query-captured TODAY/NOW semantics.

### Acquisition optimisation

Temporal expressions that can be reduced to source-field bounds should
feed 0.28 temporal-frontier inference where equivalence is provable.

## 0.29.5 - String Functions

### Add useful metadata operations

Candidate canonical functions:

``` text
TRIM
LTRIM
RTRIM
SUBSTRING
REPLACE
POSITION
STARTS_WITH
ENDS_WITH
CONCAT
CONCAT_WS
REGEXP_EXTRACT
REGEXP_REPLACE
```

Review splitting functions only if they serve common metadata workflows
and interact cleanly with typed lists.

### Unicode

-   No implicit normalisation.
-   Define length/index units consistently with existing LENGTH
    behaviour.
-   Preserve exact code-point/grapheme semantics already chosen by
    yt-sql rather than copying inconsistent dialect behaviour.

### Avoid

Do not add duplicate syntax such as `SIMILAR TO` when LIKE/ILIKE and
MATCHES already cover the useful search spaces.

## 0.29.6 - Numeric Functions

### Add a restrained analytical set

``` text
ABS
ROUND
FLOOR
CEIL
SQRT
POWER
LN
LOG
```

Review `MOD` only if ordinary arithmetic syntax does not already provide
the desired operation.

### Type rules

Preserve integer/real distinctions and deterministic conversion
behaviour.

### Avoid

No cryptographic hashes, encryption, arbitrary scientific catalogue or
specialist database numerics without a demonstrated media-query use
case.

## 0.29.7 - Aggregate and Statistical Functions

### Aggregate DISTINCT

Support where meaningful:

``` sql
COUNT(DISTINCT expr)
SUM(DISTINCT expr)
AVG(DISTINCT expr)
```

Review MIN/MAX DISTINCT and omit if semantically redundant.

### Add useful order/key aggregates

``` text
STRING_AGG
MAX_BY
MIN_BY
```

Tie semantics for MAX_BY/MIN_BY must be deterministic.

### Add statistics

``` text
MEDIAN
PERCENTILE_CONT
PERCENTILE_DISC
STDDEV_POP
STDDEV_SAMP
VAR_POP
VAR_SAMP
CORR
```

These support useful questions about duration distributions, view
statistics, upload cadence and relationships between metadata fields.

### Avoid

-   approximate count/quantile/sketch functions;
-   nondeterministic `ANY_VALUE`;
-   large specialist statistics libraries.

## 0.29.8 - Window Functions

### Ranking

``` text
ROW_NUMBER
RANK
DENSE_RANK
PERCENT_RANK
CUME_DIST
NTILE
```

### Navigation

``` text
LAG
LEAD
FIRST_VALUE
LAST_VALUE
NTH_VALUE
```

### Aggregate windows

Permit suitable existing aggregate/statistical functions as window
functions where their semantics are well defined.

### Media examples enabled

-   top N videos per year or facet;
-   rank uploads by duration within each uploader;
-   compare a video's views with the preceding upload;
-   calculate rolling/partitioned averages;
-   filter to the latest item in each logical group via QUALIFY.

### NULL handling

Review `IGNORE NULLS` / `RESPECT NULLS` after base navigation semantics
are stable.

## 0.29.9 - Stable Media and Source Identity Model

### Purpose

Expose stable Discover concepts that are currently implicit in
provenance or acquisition state.

### Candidate logical fields/functions

Review stable representations for:

-   logical source identity;
-   facet identity;
-   extractor family;
-   media ID;
-   canonical webpage/source URL;
-   playlist/channel/container identity where meaningful across
    extractors.

Prefer pseudo-fields when the value is row data. Prefer functions only
when computation or capability inspection is involved.

### Constraint

Do not expose unstable internal yt-dlp extractor class names or
transient implementation details as permanent yt-sql semantics.

## 0.29.10 - Format Metadata Model

### Purpose

Define a stable typed Discover representation for format information
obtained from yt-dlp.

### Candidate format fields

A logical format record may include, where available:

-   `format_id`;
-   `ext`/container;
-   protocol;
-   video codec;
-   audio codec;
-   width;
-   height;
-   FPS;
-   total bitrate;
-   video bitrate;
-   audio bitrate;
-   audio sample rate;
-   audio channels;
-   dynamic range/HDR indicator;
-   language;
-   filesize;
-   approximate filesize;
-   format preference/quality metadata where a stable abstraction is
    possible;
-   DRM/availability indicators only where stable and safe to expose.

### Normalisation

Translate raw yt-dlp format dictionaries into a typed logical schema.
Missing raw keys become logical NULL according to the format schema
rather than requiring users to know yt-dlp dictionary details.

### Acquisition

Format metadata must be acquired only when the query requires it.
Queries that do not inspect formats should retain opportunities for
flat/lightweight metadata acquisition.

## 0.29.11 - Format Inspection Functions

### Purpose

Provide concise media-oriented questions without requiring collection
expansion for common checks.

### Candidate functions

Review canonical names for capabilities such as:

``` text
FORMAT_COUNT
HAS_FORMAT
HAS_VIDEO
HAS_AUDIO
HAS_VIDEO_CODEC
HAS_AUDIO_CODEC
HAS_CONTAINER
HAS_HDR
MAX_WIDTH
MAX_HEIGHT
MAX_FPS
MAX_TBR
MAX_VBR
MAX_ABR
MAX_AUDIO_CHANNELS
```

Potential convenience predicates may include checking for commonly
useful codec/container combinations without encoding subjective quality
policy.

### Translation into yt-dlp

Where an inspection predicate can be represented exactly using yt-dlp's
format filtering or metadata-selection facilities, the acquisition
planner should translate it or use it to avoid irrelevant deeper work.
Where exact translation is not possible, evaluate against the typed
format collection locally.

### Avoid

Do not introduce policy-heavy functions such as `IS_4K` unless the exact
threshold and semantics are clearly preferable to simple numeric
comparison.

## 0.29.12 - Typed Metadata Collections

### Purpose

Generalise media metadata beyond scalar fields without exposing
arbitrary JSON.

### Initial scalar collections

-   tags;
-   categories.

### Initial structured collections

-   formats;
-   subtitles;
-   automatic captions;
-   chapters;
-   thumbnails.

Review other yt-dlp collections only when they are sufficiently stable
and useful.

### Type model

Collections must have known element schemas or scalar types. Raw nested
dictionaries are not implicitly queryable as generic objects.

### NULL and empty semantics

Define separately:

-   collection unavailable/NULL;
-   known empty collection;
-   populated collection.

The optimiser must also retain its separate internal state for a
collection not yet acquired.

## 0.29.13 - Collection Expansion

### Purpose

Add controlled expansion equivalent in spirit to SQL `UNNEST` and LINQ
`SelectMany`, without introducing relational JOIN.

### Candidate syntax

Choose syntax only after parser design review. A likely conceptual form
is:

``` sql
FROM @source
UNNEST formats AS format
```

### Semantics

-   one child row per collection element;
-   retain parent media identity and provenance;
-   define deterministic child order where the source collection has
    stable order;
-   NULL and empty collections produce clearly documented cardinality;
-   typed child fields participate in ordinary WHERE/GROUP BY/ORDER
    BY/window semantics.

### Media queries enabled

-   codec/container frequency;
-   available-resolution distribution;
-   subtitle-language counts;
-   chapter statistics;
-   thumbnail-dimension analysis;
-   tag/category analysis.

## 0.29.14 - Collection Predicates and Quantifiers

### Purpose

Allow common collection questions without always expanding rows.

### Candidate operations

Review a compact type-safe family equivalent to:

-   ANY;
-   ALL;
-   NONE;
-   CONTAINS;
-   CONTAINS_ALL;
-   OVERLAPS;
-   CARDINALITY;
-   DISTINCT elements.

### Syntax strategy

Prefer fixed typed functions or constrained predicate syntax initially.

Do not add a general lambda language until real collection queries
demonstrate that fixed operations are insufficient.

### Optimisation

Quantified predicates are strong candidates for yt-dlp format-filter
translation when their semantics match supported yt-dlp expressions
exactly.

## 0.29.15 - Subtitle, Caption, Chapter and Thumbnail Schemas

### Subtitle/caption logical fields

Review stable fields such as:

-   language code;
-   human-readable name where present;
-   extension/format;
-   source URL availability;
-   automatic versus authored status represented by the collection
    itself or a stable field.

### Chapter fields

-   title;
-   start time;
-   end time.

### Thumbnail fields

-   ID;
-   URL;
-   width;
-   height;
-   preference/order metadata where stable.

### Acquisition planning

Each collection should be independently demand-driven where yt-dlp
permits. Asking about formats should not force subtitle or thumbnail
acquisition unless yt-dlp's actual extractor boundary makes that
inseparable.

## 0.29.16 - Source Capability Introspection

### Purpose

Let queries reason about stable logical source capabilities when that
provides useful cross-extractor behaviour.

### Candidate questions

-   is field X structurally supported for this source/facet?;
-   is collection X supported?;
-   does this source/facet expose a particular stable logical facet?;
-   can a field be populated for this extractor family?;
-   does a source support format/subtitle/chapter metadata?

### Critical distinction

Public query semantics may expose structural support and row-level NULL
values.

Do not expose whether metadata happens to have been fetched yet.
Physical acquisition state must not change logical query results.

## 0.29.17 - Extractor-Aware Predicate Translation

### Purpose

Now that the language includes richer media predicates, expand the 0.28
pushdown system to translate exact query intent into yt-dlp where
possible.

### Candidate translation areas

-   date ranges;
-   playlist/item ranges;
-   format filters;
-   match filters;
-   live/upcoming state where yt-dlp exposes exact stable filtering;
-   metadata field requirements;
-   subtitle/caption/format acquisition switches;
-   flat versus deep extraction;
-   source/facet navigation.

### Rules

-   Translation must be semantics-preserving.
-   Unsupported translation falls back to local evaluation, not altered
    results.
-   Explain output should show what was translated and what remains
    local.
-   Version-specific yt-dlp syntax remains adapter implementation
    detail.

## 0.29.18 - Advanced Grouping and Collection Review

### Review individually

-   `GROUPING SETS`;
-   `ROLLUP`;
-   `CUBE`;
-   ordered-set aggregates;
-   `ARRAY_AGG` or a typed collection aggregate;
-   list slicing/indexing;
-   map/object structures if any real extractor use case cannot be
    represented by stable typed records.

### Expected bias

`ROLLUP` and `GROUPING SETS` may be useful for media summaries. `CUBE`
is likely unnecessary unless real multidimensional reporting use cases
appear.

Do not adopt the family wholesale.

## 0.29.19 - Remaining SQL and LINQ Value Review

### Purpose

Repeat the cross-dialect review after the implemented features exist and
evaluate any remaining gaps against real Discover workflows.

### Areas to reconsider

-   additional useful scalar functions;
-   additional date/time operations;
-   first/last/top-by-key patterns;
-   sequence operators inspired by LINQ;
-   collection projection/filtering without full lambda syntax;
-   additional set or ranking operations;
-   query constructs that can translate efficiently into yt-dlp.

### Explicitly rejected unless new evidence changes the decision

-   JOIN and relational cross-products;
-   DML/DDL;
-   transactions/indexes/constraints;
-   stored procedures/triggers;
-   recursive CTEs;
-   MATCH_RECOGNIZE;
-   PIVOT/UNPIVOT as a priority;
-   approximate analytics;
-   database-style TABLESAMPLE without extractor support;
-   generic JSON mutation/query programming;
-   XML;
-   hashing/encryption;
-   spatial/GIS;
-   networking/IP functions;
-   database administration functions;
-   machine-learning SQL extensions;
-   arbitrary shell execution;
-   aliases added only for dialect compatibility.

## 0.29.20 - Features and Fluctuations Reconciliation

### Scope

Perform a complete post-expansion language and optimiser audit.

### Documentation

Update and reconcile:

-   `YT-SQL.md`;
-   `YT-SQL-OPTIMISATION.md`;
-   `YT-SQL-TEST-COVERAGE.md`;
-   `DISCOVER-README.md`;
-   `TODO.md`;
-   examples/help output;
-   deterministic dataset/conformance documentation.

### Testing

Require comprehensive coverage of every new construct across:

-   parsing;
-   resolution;
-   execution;
-   formatting;
-   malformed input;
-   NULL;
-   Unicode;
-   optimiser equivalence;
-   source/facet composition;
-   CTE/set composition;
-   nested collections;
-   acquisition translation;
-   deterministic diagnostics.

### Completion criterion

0.29.x is complete when yt-sql is a coherent media-metadata query
language rather than a collection of SQL-inspired additions, and every
accepted media-specific feature composes correctly with the acquisition
optimiser.

## Roadmap maintenance

This file is a living programme document. As each sub-phase is
completed, mark it complete and reconcile the description with durable
implemented behaviour. Keep transient local-acceptance notes out of
committed product documentation. During an active version series,
structural cleanup may be deferred until the series closes, at which
point stale notes, duplicated TODOs and obsolete transitional wording
should be removed.

The canonical location for these programme documents is `docs/roadmap/`.
