# yt-discover raw metadata audit

This document records the Part 1 audit for GitHub issue #130. It describes the accepted `raw.*` contract before storage or language changes are made.

## Scope

`raw.*` is an established yt-sql language surface, not merely the SQLite `raw_json` column. The accepted implementation stores the backend response in each normalised record as `_raw`, infers dynamic field structure from observed backend values, resolves `raw.*` paths at runtime, plans open-ended raw acquisition separately, and exercises the surface throughout parser, semantic, evaluator, projection, collection, conformance, help and documentation tests.

Part 1 deliberately does not select provider-specific namespace syntax and does not remove `raw_json`.

## Accepted language behaviour

The current contract includes dotted paths such as `raw.extra.score`, quoted identifiers below `raw`, postfix structured-member access such as `(raw.record).provider_id`, collection indexing such as `raw.keywords[0]`, nested collection indexing, and collection expressions over raw values.

Dynamic raw structure is inferred conservatively from observed records. Compatible scalar values, structured records and collections can become queryable. Mixed or incompatible runtime shapes remain unresolved rather than being silently coerced. Structured collections have separate restrictions around whole-value projection and positional access.

Star expansion excludes `raw.*`, while explicit raw projections remain supported when their resolved type is selectable.

## Planner and acquisition behaviour

The acquisition planner recognises `raw.*` as open-ended metadata and assigns it to the `dynamic-raw` stage. This means removing raw persistence cannot be treated as a cache-only refactor. A replacement must give registered fields sufficient provider, acquisition-group and freshness information for the planner to request the same useful metadata deliberately.

## Persistence boundary

v3 persists the complete authoritative backend response in `metadata_records.raw_json`. Normalisation retains that response as `_raw`, which is the data source used by dynamic `raw.*` schema inference and evaluation.

Cache v4 already has a different model: logical fields are registered by providers with explicit yt-sql types, storage names, acquisition groups and freshness policies. Provider metadata tables store declared scalar fields rather than arbitrary backend responses. Issue #130 should move useful queryable metadata towards that registered model instead of recreating a generic raw-response blob.

## Inventory classification

### Existing registered or stable logical metadata

The ordinary schema already exposes stable scalar fields including identity, title, upload/release timestamps, duration, engagement counts, channel/uploader identity, live/availability state, URL and playlist/source position. It also has stable collection contracts for `tags`, `categories`, `formats`, `chapters` and `thumbnails`.

Where a real `raw.*` query merely reaches data that has an equivalent stable logical field, the registered logical field is the preferred v4 destination. The migration must not duplicate such material solely to preserve its backend spelling.

### Useful metadata requiring registry work

The audit finds accepted tests and examples using dynamic scalar, structured and collection material that is not represented by the current stable field catalogue. Representative shapes include `raw.extra.score`, `raw.keywords`, provider records with nested members, nested scalar collections and fixture-specific raw fields.

These examples prove language capabilities, but they do not by themselves prove that every fixture field deserves production registration. Part 2 must inventory real backend metadata separately from synthetic conformance fields and register only useful queryable metadata with an explicit type, provider, acquisition group and freshness policy.

### Backend baggage eligible for deliberate discard

Backend response material with no accepted query/documentation use and no justified registered metadata role should not be carried into v4 merely because it existed in `raw_json`. Discarding it is an explicit compatibility decision and must be counted separately from material normalised into registered v4 metadata.

No Part 1 evidence supports retaining an arbitrary backend-response blob as a v4 escape hatch.

## Surfaces that must change together

A complete #130 implementation must reconcile all of the following surfaces:

- v3 cache persistence and migration accounting;
- cache-v4 provider field registration and typed provider storage;
- dynamic schema inference and raw-path resolution;
- parser qualification, quoted identifiers and postfix/member syntax;
- evaluator runtime lookup and missing-value guards;
- projection and collection semantics;
- acquisition planning and the `dynamic-raw` stage;
- CLI schema/help/examples;
- yt-sql documentation and optimisation documentation;
- deterministic conformance fixtures and parser/evaluator/planner regression tests.

## Migration accounting requirement

Migration must distinguish at least these outcomes:

1. recognised backend material normalised into registered v4 metadata;
2. recognised material already represented by an equivalent stable logical field;
3. backend-only material deliberately discarded;
4. material that cannot yet be classified safely and therefore blocks destructive retirement.

A migration must not report successful normalisation merely because a legacy `raw_json` row was read or deleted.

## Namespace decision

Part 1 does not choose syntax for provider-specific or genuinely dynamic fields. If later work proves that such a language surface is required, its grammar must compose with existing qualification, quoted identifiers, member access, collection indexing and other postfix syntax. It requires parser, formatter, semantic, evaluator and conformance treatment equivalent to other yt-sql syntax.

## Part 1 conclusion

The arbitrary persisted backend response is not an appropriate cache-v4 storage primitive. However, deleting it before replacing the useful language-visible metadata would regress an established yt-sql contract.

Part 2 should therefore build the concrete registered-metadata replacement and migration accounting from this inventory. Language compatibility decisions should follow the field inventory rather than precede it.

## Part 2 registered-metadata implementation

The first concrete replacement provider is now registered as `yt-dlp`. Stable scalar metadata is declared with yt-sql types, a detailed-metadata acquisition group, storage names and freshness policies instead of relying on an arbitrary backend response for v4 persistence. Typed datetime fields use lossless SQLite TEXT affinity while retaining their yt-sql datetime contract.

During the compatibility period, accepted v3 detailed-cache writes are also normalised into the v4 yt-dlp provider table and successful detailed acquisition state is recorded. The legacy `raw_json` row remains in place for the existing `raw.*` language path until the later compatibility and runtime-cut-over parts.

Migration accounting is persisted per source and media identity. It separately counts registered scalar fields, collection material already represented by stable logical fields, and backend-only fields deliberately discarded from v4 registered persistence. Internal `_yt_sql_` provenance keys are not counted as discarded backend material.

The current stable collection fields remain an explicit follow-on storage concern. Part 2 accounts for `tags`, `categories`, `formats`, `chapters` and `thumbnails` as stable logical equivalents rather than serialising them into scalar provider columns or falsely reporting them as discarded baggage.

## Part 3 compatibility transition

Simple `raw.<field>` references now recognise stable logical metadata before consulting the arbitrary backend payload. This preserves established scalar query spellings such as `raw.title`, `raw.duration` and `raw.views` while allowing those expressions to be satisfied by the normal registered record representation.

The mapping is deliberately narrow. Only a single raw path component that resolves to a known stable scalar field or alias is redirected. Stable collections are not redirected because their existing raw structured and indexing semantics are not interchangeable with the logical collection contract. Nested paths such as `raw.extra.score`, provider-shaped structured values and other genuinely dynamic raw material retain the legacy dynamic schema and evaluator path for this compatibility stage.

Acquisition planning applies the same distinction. Stable raw spellings are planned as their canonical logical field and therefore no longer force the open-ended `dynamic-raw` stage. Genuinely dynamic raw paths continue to require that stage.

No provider-specific namespace syntax is introduced. The remaining dynamic raw surface still demonstrates a real compatibility requirement, but Part 3 does not establish that a new namespace is the correct long-term language design. That decision remains coupled to the final runtime cut-over and explicit compatibility policy.
