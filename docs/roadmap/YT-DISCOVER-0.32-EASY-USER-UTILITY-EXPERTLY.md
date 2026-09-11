# yt-discover 0.32.x - Easy User Utility, Expertly

## Status of release name

"Easy User Utility, Expertly" is a working release-series name and may be reviewed or replaced before implementation.

## Purpose

The 0.32.x series makes the mature Discover engine easier to use without diluting expert control or making query behaviour implicit. Usability work follows the refactor, optimiser and feature programmes so it can expose stable capabilities rather than designing interfaces around moving internals.

The tool remains suitable for scripting and internal use. Human convenience must not damage deterministic execution, machine-readable behaviour or reproducibility.

## 0.32.0 - Query Files

### Add

First-class execution of `.yt-sql` files.

### Requirements

-   UTF-8 input;
-   deterministic file reading;
-   precise filename/line/column diagnostics;
-   parameter support consistent with inline queries;
-   same parser/resolver/execution pipeline as command-line query text;
-   no separate query-file dialect;
-   clear behaviour for BOM and line endings;
-   safe handling of missing/unreadable files.

### Possible CLI surface

Choose spelling during implementation, but avoid ambiguous positional behaviour. The file path should be explicitly distinguishable from a literal query when necessary.

## 0.32.1 - Saved Queries

### Purpose

Allow frequently used queries to be named without duplicating long command lines.

### Requirements

-   simple inspectable storage;
-   query text remains ordinary yt-sql;
-   named query may declare expected parameters where useful;
-   explicit CLI arguments/parameters remain visible at execution time;
-   no hidden mutation of query semantics;
-   deterministic lookup rules;
-   safe handling of duplicate names;
-   export/import should be possible through ordinary files rather than proprietary opaque state.

### Non-goal

Do not create a database-backed query library unless ordinary files prove insufficient.

## 0.32.2 - Persistent Configuration

### Scope

Add configuration only for repetitive non-query policy.

Candidate settings may include:

-   cache policy/location;
-   output defaults;
-   preferred explain verbosity;
-   common source adapter policy;
-   user interface defaults that do not alter the logical meaning of a query unexpectedly.

### Precedence

Define and test a clear precedence such as:

``` text
built-in defaults
  < configuration
  < environment variables where explicitly supported
  < command-line arguments
```

### Reproducibility

Provide a way to inspect effective configuration. Avoid settings that make a copied query impossible to understand without hidden local state.

## 0.32.3 - Shell Completion

### Scope

Provide generated or maintained completion for stable CLI surfaces.

Initial shells may include those common on supported development environments, with Bash/Zsh/Fish considered according to maintenance cost.

### Completion candidates

-   CLI options;
-   named saved queries;
-   stable facets;
-   configuration keys;
-   perhaps yt-sql keywords/functions where shell context makes this practical.

### Non-goal

Do not implement a shell parser or fragile context engine merely to complete arbitrary SQL expressions.

## 0.32.4 - Diagnostic and Error Presentation

### Improve

-   precise source spans;
-   deterministic expected-token messages;
-   near-match suggestions for fields/functions/facets;
-   capability-aware errors for unsupported fields/collections;
-   query-file filename and line information;
-   clearer type mismatch diagnostics;
-   clearer distinction between source-capability failure and row-level NULL data;
-   collection/schema errors that show the logical Discover schema rather than raw yt-dlp internals.

### Constraints

-   Keep error messages deterministic enough for automated tests.
-   Do not change machine-readable error contracts merely for prettier prose.
-   Avoid speculative suggestions when multiple interpretations are equally plausible.

## 0.32.5 - Discovery and Introspection Helpers

### Purpose

Make the language discoverable without requiring documentation lookup for every stable capability.

### Candidate commands/modes

-   list logical fields;
-   list scalar/aggregate/window/media functions;
-   list supported facets for a source where capability discovery is available;
-   describe a logical source/facet schema;
-   describe metadata collections and child fields;
-   canonicalise/format a query;
-   validate a query without acquisition;
-   explain a query plan;
-   show which predicates/requirements can be translated into yt-dlp;
-   show acquisition stages implied by a query.

### Output

Provide human-readable output and machine-readable forms where the information is likely to be consumed by tooling.

## 0.32.6 - Query Authoring Assistance

### Scope

Add lightweight facilities that help users construct correct queries without creating a full IDE.

Candidates:

-   function signatures and type summaries;
-   field/schema lookup;
-   examples attached to introspection output;
-   query validation;
-   canonical formatting;
-   warnings for semantically valid but acquisition-expensive patterns where the planner can justify the warning.

### Constraint

Performance advice must be grounded in the actual physical plan. Do not emit generic SQL folklore such as warnings about constructs that are cheap in Discover's architecture.

## 0.32.7 - Machine-Readable Query Contract

### Purpose

Evaluate and, if justified, expose a versioned language-neutral representation for resolved/validated Discover queries or physical plans.

### Potential consumers

-   scripts;
-   editors;
-   other programming languages;
-   automation systems;
-   later Discover-to-Downloader interchange tooling.

### Requirements

-   versioned schema;
-   explicit types;
-   no arbitrary shell command strings;
-   compilation through the same semantic resolver/planner as CLI queries;
-   deterministic validation errors;
-   compatibility policy;
-   clear distinction between logical query and physical acquisition plan.

### Relationship to compiled query investigation

If the earlier compiled/serialised query investigation demonstrates value, align the machine contract with it without making the on-disk representation an opaque implementation dump.

## 0.32.8 - Explain and Plan UX

### Purpose

Make the substantial 0.28 optimiser and 0.30 language behaviour understandable to expert users.

### Human explain should answer

-   what logical sources/facets are queried?;
-   what fields/collections are required?;
-   what can be decided before deep acquisition?;
-   what is translated into yt-dlp?;
-   what remains local?;
-   what metadata stages are required?;
-   can acquisition terminate early?;
-   why was an apparently useful optimisation rejected?;
-   which operation dominates expected acquisition cost where the planner can justify such a statement?

### Machine explain

Keep a stable versioned structure suitable for testing and tooling.

## 0.32.9 - Usability Reconciliation

### Scope

Review Discover as a complete user-facing tool after the engine and language have stabilised.

### Documentation

Reconcile:

-   `DISCOVER-README.md`;
-   `YT-SQL.md`;
-   help output;
-   `--examples` output;
-   query-file documentation;
-   saved-query documentation;
-   configuration documentation;
-   explain/introspection documentation;
-   machine-interface documentation if implemented.

### Quality requirements

-   Help and `--examples` continue to contain thorough practical examples.
-   Examples cover ordinary metadata queries and media-native features such as formats, collections and windows.
-   Every documented command is exercised by automated tests where deterministic.
-   Human conveniences never change machine-readable modes unexpectedly.
-   No implemented feature remains listed as future work in TODO.

## Series-wide non-goals

-   GUI;
-   background scheduler;
-   media-library database;
-   opaque cloud state;
-   arbitrary shell hooks;
-   plugin framework without a concrete need;
-   hiding expert behaviour behind automatic rewriting that cannot be explained or reproduced.

## Roadmap maintenance

This file is a living programme document. As each sub-phase is completed, mark it complete and reconcile the description with durable implemented behaviour. Keep transient local-acceptance notes out of committed product documentation. During an active version series, structural cleanup may be deferred until the series closes, at which point stale notes, duplicated TODOs and obsolete transitional wording should be removed.

The canonical location for these programme documents is `docs/roadmap/`.
