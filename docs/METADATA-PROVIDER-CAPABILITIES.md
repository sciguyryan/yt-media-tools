# Metadata provider capabilities

Discover's logical and semantic planning determines what metadata a query requires. Provider selection is a later physical concern: it may choose how an established requirement is satisfied, but it must not change the requirement or yt-sql's interpretation of the resulting value.

## Contract

`MetadataRequirement` projects an existing physical acquisition stage and its required fields into provider-selection form. `ProviderCapability` declares one provider's ability to satisfy a stage, optionally limited to a finite set of fields. A capability also records semantic authority, applicable resolved source kinds, supported authentication modes, acquisition granularity, a relative physical cost rank and a stable provenance identity.

Only exact capabilities are eligible to satisfy an authoritative requirement. Approximate values remain useful elsewhere in acquisition and planning, but a lower cost must never promote them to exact metadata. A finite field capability is eligible only when it covers every field in the requirement.

Source-specific capabilities are conservative. They are ineligible while source identity is unresolved and remain ineligible when the resolved source kind does not match. This establishes the boundary needed for later source/extractor resolution work without guessing platform identity from a URL.

Authentication is also part of eligibility. Anonymous and cookie-authenticated acquisition are distinct capabilities. User-supplied cookies remain supported where a provider can consume them, but credential contents are not provider metadata and must never become provenance, cache data or explain output.

## Deterministic selection

Eligible exact capabilities are ordered by physical cost rank and then stable provider/provenance identity. Cost is deliberately only a physical hint. It cannot override authority, field coverage, source applicability or authentication requirements.

The initial selector returns the preferred capability and the complete ordered candidate set. It does not yet alter Discover's execution path. Existing yt-dlp and YouTube.js behaviour therefore remains unchanged while provider candidates are benchmarked and registered in later work.

The current relative cost rank is intentionally abstract rather than a timing estimate. Concrete provider integrations should derive useful ranks from reproducible measurements and should expose enough reasoning for later explain integration.

## Relationship to the physical acquisition plan

`PhysicalAcquisitionPlan.provider_requirements` derives provider requirements directly from required acquisition stages, including whole fields, indexed fields, structured-member requirements and collection-query requirements. The existing acquisition plan remains the single semantic source of truth.

This gives later lowering a stable direction:

```text
logical query requirements
        ↓
physical acquisition stages
        ↓
metadata provider requirements
        ↓
eligible exact provider capabilities
        ↓
deterministic physical provider choice
```

Provider resolution and provider acquisition remain separate concepts. A future backend may identify a source while a different eligible provider satisfies some of its metadata requirements.

## Deliberate exclusions

This foundation does not register new providers, change runtime acquisition, introduce automatic multi-provider execution, reconcile disagreements between authoritative providers, or add official platform developer APIs. Those remain separate follow-up work so that provider experiments cannot silently change established query behaviour.

## Backend resolution evidence

Backend-reported extractor resolution is documented in [BACKEND-SOURCE-RESOLUTION.md](BACKEND-SOURCE-RESOLUTION.md). The capability selector deliberately accepts resolved source identity as context without deriving it from URL appearance.

## Resolution-aware eligibility

`selection_context_from_backend_resolution()` connects observed backend resolution to provider selection without guessing from the original source expression. A single unambiguous non-generic yt-dlp extractor family may constrain specialised provider capabilities. Generic, missing or conflicting resolution remains unknown and therefore excludes source-specific providers while leaving generic capabilities available.

This is intentionally one-way physical evidence. The selected extractor family does not change logical source identity or yt-sql meaning, and a cheaper specialised provider cannot become eligible from URL or domain appearance alone. Authentication requirements are carried alongside the resolved source kind and remain independently mandatory.

## Issue #113 production-candidate boundary

The completed provider investigations are reconciled in [METADATA-PROVIDER-RECONCILIATION.md](METADATA-PROVIDER-RECONCILIATION.md). Issue #113 recommended separate production-integration work for a narrow authoritative YouTube.js known-video scalar capability and for specialised ytmusicapi acquisition after conservative music-source resolution. Issue #114 now registers the first of those capabilities as physical planning data without changing yt-sql semantics or promoting the experimental benchmark adapter wholesale.

The same reconciliation defers youtube-innertube, pytubefix and NewPipeExtractor because the retained evidence does not demonstrate a concrete production advantage sufficient to justify another runtime path. Automatic public-instance Invidious and Piped acquisition is rejected on the observed operational evidence while explicitly configured operator-controlled deployments remain research possibilities.

## Issue #114 YouTube.js exact-scalar capability

The production capability registry advertises `youtubejs:getBasicInfo` only for `id`, `title`, `channel_id`, `duration` and `view_count` at the complete-metadata stage. Eligibility additionally requires conservative backend resolution to the `youtube` extractor family. Anonymous and existing cookie-authenticated contexts are supported, but credential material is never part of the capability or provenance record.

The field set is intentionally closed. `upload_date`, `date`, live/private/unlisted state, descriptions, keywords and other values exposed by the underlying library are not authoritative merely because `getBasicInfo()` can return them. A requirement containing any uncovered field makes this capability ineligible as a complete satisfier, preserving the established acquisition path for that requirement.

This first #114 step establishes the production authority and eligibility contract. Runtime lowering and acquisition must consume this contract rather than duplicating the field list or inferring additional authority from provider output.

## Issue #114 publication-date investigation

The discontinued human authority assessment and temporary raw-response diagnostics established an important boundary but are not retained as production machinery. The follow-up upstream investigation found no evidence that `PlayerMicroformat` itself nullifies populated `publishDate` or `uploadDate` values. Instead, YouTube.js `MediaInfo.basic_info` deliberately copies only a subset of player-microformat properties and does not propagate `publish_date` or `upload_date`. This explains why the benchmark's `basic_info` normalisation could not expose those values.

Publication dates remain outside the #114 capability. A provider-native timestamp must not silently become yt-sql's date-only `upload_date` until the required timezone and calendar-date semantics are explicitly established. The production lowering layer therefore selects YouTube.js only when an entire `complete-metadata` requirement is contained within the accepted five-field exact-scalar set. Unsupported or mixed requirements are left on the established acquisition path rather than being partially lowered. Wholly lowered exact-scalar requirements now execute through the production YouTube.js `getBasicInfo()` bridge after conservative backend source resolution. Bridge failure or an omitted individual video falls back to yt-dlp. Specialised partial rows are deliberately not written into the existing detailed metadata cache because that cache currently represents full yt-dlp-style records; allowing a five-field row to replace a richer cached record would be a semantic regression. Cache/provenance unification remains separate from the provider authority decision.

### Production explain and provenance visibility

Offline explain output reports specialised provider opportunities as conditional physical lowering. Source-specific capabilities such as `youtubejs:getBasicInfo` remain marked as requiring runtime source resolution because static query explanation does not have the extractor-family evidence used by production selection. The established acquisition path remains explicit as the fallback.

Runtime provenance records provider and operation counts only when an acquired row carries explicit specialised-provider attribution. Untagged rows are deliberately reported as unattributed because they may originate from yt-dlp or the existing metadata cache, and provenance must not guess an origin that the execution path did not preserve.

### Production session reuse

Production `getBasicInfo()` acquisition passes the complete requested metadata batch to one bridge process. The bridge creates one Innertube session before iterating the video IDs and reuses that session for every item in the batch. This preserves the session-reuse behaviour measured during the provider investigation without introducing cross-query global state, background pooling or provider-specific semantics into the planner. LIMIT-aware acquisition may still create separate sessions for separate semantic batches because those batches are deliberately evaluated incrementally and may terminate early.
