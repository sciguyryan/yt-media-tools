# Detailed metadata acquisition audit

## Purpose

This document records the Phase 3 audit for issue #81. It identifies the metadata requirements that move Discover from lightweight enumeration into detailed per-video extraction, characterises the current cost boundaries, and records optimisation opportunities to investigate before adding another metadata provider.

## Current acquisition boundary

Discover partitions query requirements by semantic authority rather than by whether a backend happens to expose a value. Exact lightweight fields may be evaluated after enumeration. Approximate lightweight values are not promoted to authoritative query values and remain detailed requirements when exact semantics are required.

The stable scalar capability declarations currently make `id`, `title` and `source_index` authoritative during lightweight enumeration. `upload_date`/`date`, `duration`, `view_count`/`views` require detailed extraction for authoritative values. YouTube.js supplies exact identity/title information and approximate dates where available, while duration is not supplied by that path. yt-dlp flat enumeration supplies approximate duration and the same approximate date/view-count families, but those values remain insufficient for authoritative evaluation.

Known scalar fields outside that explicitly lightweight set, known collection fields, and dynamic `raw.*` fields conservatively require detailed metadata. Structured collection stages such as formats, subtitles, chapters, thumbnails, tags and categories remain explicit in the backend-neutral physical plan even though the current yt-dlp lowering collapses them into the same complete JSON extraction phase.

This is an important semantic boundary. A field being present in lightweight output is not evidence that Discover may use it as an exact value.

## Current detailed path

For a known set of YouTube video IDs, Discover constructs one yt-dlp invocation containing each watch URL and requests full JSON metadata with downloads disabled. The detailed path therefore avoids one yt-dlp process per video, but yt-dlp still performs detailed extraction for each requested video within that invocation.

Before extraction, the metadata cache performs a source-scoped bulk lookup. Fresh rows satisfying the required detailed fields are reused and only stale or missing IDs are passed to yt-dlp. Freshly acquired records are written back in bulk. Exact lightweight fields are subsequently overlaid from enumeration so cache freshness for the detailed pass only needs to cover detailed-only requirements.

Safe LIMIT/OFFSET early termination has a separate batching boundary. Eligible source-order queries acquire detailed candidates in batches of 25 and stop once enough authoritative matches have been proven. This batching is a query-semantic optimisation, not a general detailed-extraction performance setting, and should not be changed merely to reduce process overhead.

## Principal cost boundaries

The audit identifies these current cost centres and constraints:

1. Detailed extraction is coarse-grained at the yt-dlp backend boundary. Once any deeper semantic stage is required, the current lowering requests complete JSON extraction for each cache-miss/stale candidate.
2. Several lightweight fields are available only approximately. `upload_date`/`date`, `duration` and `view_count`/`views` can therefore trigger detailed extraction even when no collection or dynamic metadata is requested.
3. Collection and dynamic requirements collapse to the same complete yt-dlp extraction. The physical plan distinguishes them, but the current backend cannot exploit that distinction to acquire only the requested family.
4. Cache reuse already removes fresh candidates before detailed extraction. Any alternative path must preserve source-scoped cache identity, required-field freshness and provenance rather than bypassing this work.
5. LIMIT-aware detailed acquisition intentionally uses 25-candidate batches so semantic early termination can avoid later candidates. Combining those batches into one unbounded invocation would trade away proven work avoidance.
6. The normal detailed command is already bulk at the process level: one yt-dlp process receives the complete known ID set for that acquisition pass. Replacing it with another mechanism should therefore be justified by cheaper per-ID metadata acquisition, stronger batching inside the provider, narrower field acquisition, or another measurable benefit rather than process-count assumptions.

## Existing opportunities before another backend

The current architecture exposes several optimisation questions that should be investigated before adding a provider:

- Determine whether yt-dlp has a supported extraction mode or API path that can satisfy exact scalar-only requirements more cheaply than complete JSON extraction while preserving the same semantics and failure handling.
- Measure how much detailed work is caused by exact scalar requirements versus collections, structured metadata and dynamic raw fields on representative queries.
- Determine whether additional YouTube.js/Innertube values can be declared exact for specific fields based on a defensible semantic and provenance contract. Do not promote approximate values merely because they appear stable in samples.
- Investigate whether detailed acquisition can consume the backend-neutral stage distinctions more selectively instead of collapsing every deeper stage to complete JSON extraction.
- Preserve cache filtering before any expensive provider call. Provider-specific batching should operate on the already reduced cache-miss/stale candidate set.
- Preserve LIMIT-aware work avoidance. A faster bulk provider may justify a different physical strategy only after its cost and semantic trade-offs are measured explicitly.

These are investigation targets, not accepted optimisations. No capability declaration or acquisition behaviour changes in this phase.

## Measurements needed for backend comparison

Issue #98 subsequently compared candidate mechanisms against this baseline using representative fixed ID sets and query requirement classes. The investigation criteria required measurements to distinguish:

- exact scalar-only detailed requirements;
- collection metadata requirements;
- dynamic raw metadata requirements;
- cold-cache and warm/partially warm-cache acquisition;
- bounded LIMIT-aware acquisition and full candidate acquisition;
- authenticated/cookie-dependent and unauthenticated behaviour where applicable;
- successful, unavailable and partially failing candidate sets.

Useful measurements include provider calls or requests, elapsed acquisition time, candidates attempted, authoritative records returned, failure classification, bytes or payload size where observable without intrusive instrumentation, and cache writes/reuse. Performance results should not weaken semantic or provenance requirements.

## Phase 3 conclusion

The current detailed path is not simply spawning yt-dlp once per candidate. It already performs bulk process invocation for a known ID set, bulk cache lookup/write, and safe LIMIT-aware batching where query semantics permit early termination. The larger opportunity is reducing the cost or breadth of authoritative per-video extraction after cache filtering.

Issue #98 therefore investigated alternatives against specific requirement classes rather than asking which library could generally fetch YouTube metadata. A useful alternative had to satisfy authoritative fields more cheaply, batch known IDs more effectively, acquire narrower semantic stages, or materially improve reliability while fitting the existing backend-neutral plan and cache/provenance model.

The completed Phase 4 investigation and its descendant provider evidence are reconciled in `METADATA-BACKEND-INVESTIGATION.md` and `METADATA-PROVIDER-RECONCILIATION.md`. This audit remains the pre-investigation baseline and should not be read as a description of the later specialised production capabilities.
