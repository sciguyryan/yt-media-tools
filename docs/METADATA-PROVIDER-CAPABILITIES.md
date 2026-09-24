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

The completed provider investigations are reconciled in [METADATA-PROVIDER-RECONCILIATION.md](METADATA-PROVIDER-RECONCILIATION.md). Issue #113 recommends separate future production-integration work for a narrow authoritative YouTube.js known-video scalar capability and for specialised ytmusicapi acquisition after conservative music-source resolution. It deliberately does not register either capability here.

The same reconciliation defers youtube-innertube, pytubefix and NewPipeExtractor because the retained evidence does not demonstrate a concrete production advantage sufficient to justify another runtime path. Automatic public-instance Invidious and Piped acquisition is rejected on the observed operational evidence while explicitly configured operator-controlled deployments remain research possibilities.
