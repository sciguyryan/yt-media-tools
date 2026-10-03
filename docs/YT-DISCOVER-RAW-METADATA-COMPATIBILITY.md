# yt-discover raw metadata audit

This document records the architectural history of the former `raw.*` yt-sql surface and explains why it was removed before release.

## Historical problem

Cache v3 stores the complete yt-dlp response in `metadata_records.raw_json`. During the cache-v4 design work, `raw.*` was a real yt-sql feature rather than a debugging convenience: parsing, schema inference, evaluation, acquisition planning, collections, examples and tests could expose arbitrary nested extractor material.

That created a genuine migration question. Removing the v3 JSON blob without making an explicit language decision would have changed query behaviour accidentally, so the early v4 work audited raw metadata and temporarily preserved unresolved source-scoped compatibility material while registered metadata moved into the provider model.

## What the audit established

The useful long-lived boundary is registered metadata, not arbitrary extractor response shape. Stable scalar fields belong to provider definitions with explicit yt-sql types, acquisition groups and freshness policies. The supported collection families `tags`, `categories`, `formats`, `chapters` and `thumbnails` likewise have explicit language contracts and closed v4 persistence.

The audit also exercised synthetic dynamic scalar, structured and collection values. Those cases proved that the language machinery could support open-ended backend data, but they did not establish a production need for doing so. An extensive pre-release usage review found no actual use of `raw.*` in this internal tool.

Preserving the feature would therefore have required Discover to retain arbitrary backend-shaped material, provenance and freshness semantics, migration and certification rules, maintenance handling, dynamic schema behaviour and a substantial test surface without a demonstrated use case. That cost conflicts with the central v4 rule: this is a Discover cache, not a general provider object store.

## Final decision

Issue #142 removes `raw.*` before public release. There is no deprecation mode or replacement generic provider namespace. A query that attempts to use the removed namespace is rejected and should use a registered yt-sql field instead.

Normal runtime records no longer retain a private copy of the complete extractor response for raw-path evaluation. Cache v4 contains no generic raw compatibility payload or migration-accounting table. Unknown backend fields have no v4 persistence merely because yt-dlp returned them.

Historical v3 `raw_json` remains valid migration input. The v3-to-v4 transition reads it to reconstruct supported registered scalar facts and the five supported collection families, then deliberately discards unregistered remainder. This is a one-way interpretation of historical source facts, not a promise to preserve the v3 representation.

Fresh-v4 and migrated-v4 databases therefore converge on the same target schema. Registered metadata, provider/acquisition state, source state, provenance and supported collections survive according to their explicit contracts; arbitrary backend baggage does not.

## Why the history remains documented

The temporary compatibility design was useful. It prevented the cache migration from silently deciding a language question, forced a concrete inventory of registered versus arbitrary metadata, and gave the migration work a conservative intermediate boundary while v4 storage was still being built.

Removing that compatibility layer later in development does not make the earlier reasoning wrong. The evidence changed: once the complete v4 path existed and actual usage was reviewed, the open-ended feature no longer justified its continuing architectural cost. Keeping this history makes the final schema easier to understand without presenting superseded compatibility machinery as current behaviour.

Any future proposal for provider-specific or otherwise dynamic metadata should start from a demonstrated query use case and define its type, acquisition, freshness, persistence and migration semantics explicitly. It should not restore arbitrary backend-response access as an escape hatch.
