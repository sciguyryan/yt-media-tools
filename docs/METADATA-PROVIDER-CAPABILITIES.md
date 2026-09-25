# Metadata provider capabilities

Discover separates yt-sql semantics from physical metadata acquisition. Logical and semantic planning establishes the metadata a query requires; provider selection then chooses an eligible authoritative implementation without changing the requirement or the meaning of the resulting value.

## Capability contract

`MetadataRequirement` projects an existing physical acquisition stage and its required fields into provider-selection form. `ProviderCapability` declares a provider's authority for a stage, optionally restricted to a finite field set, together with applicable resolved source kinds, required source traits, supported authentication modes, acquisition granularity, relative physical cost and stable provenance identity.

Only exact capabilities may satisfy authoritative requirements. Approximate values can inform bounded acquisition and planning but cannot become authoritative merely because they are cheaper. A finite-field capability is eligible only when it covers the complete requirement presented to that stage.

Source-specific capabilities require conservative backend resolution. URL appearance alone is not evidence of source identity. Authentication is also part of eligibility: anonymous and cookie-authenticated contexts are distinct, and credential material must never become provider metadata, provenance, cache data or explain output.

## Physical selection

The physical acquisition plan remains the semantic source of truth. Provider lowering follows this direction:

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

Eligible capabilities are ordered by relative physical cost and then stable provider/provenance identity. Cost is a physical hint only. It cannot override authority, field coverage, source applicability, source traits or authentication requirements.

Provider resolution and provider acquisition are separate concerns. One backend may establish conservative source evidence while another eligible provider satisfies metadata requirements. Provider-specific fields and operations remain below the yt-sql boundary unless Discover deliberately defines provider-neutral semantics for them.

## Backend resolution and source traits

Backend resolution is described in [BACKEND-SOURCE-RESOLUTION.md](BACKEND-SOURCE-RESOLUTION.md). `selection_context_from_backend_resolution()` converts unambiguous non-generic yt-dlp extractor-family evidence into physical provider-selection context. Missing, generic, conflicting or mixed-provider resolution remains unknown and therefore excludes source-specific providers while leaving generic capabilities available.

Positive source traits provide a second conservative eligibility dimension. Traits must be established independently of the specialised provider whose eligibility they control. Absence of a trait is unknown rather than evidence of its negation.

The current `music` trait requires yt-dlp to resolve the source through the YouTube extractor family and every observed original source domain in the acquisition batch to be `music.youtube.com`. A raw Music URL, generic extractor result, mixed origins, absent origin evidence, ytmusicapi success, `musicVideoType` or playback eligibility cannot establish the trait by themselves.

## YouTube.js exact-scalar capability

The production `youtubejs:getBasicInfo` capability is authoritative only for `id`, `title`, `channel_id`, `duration` and `view_count` at the complete-metadata stage. It requires conservative resolution to the `youtube` extractor family and supports anonymous and existing cookie-authenticated contexts.

The field set is closed. Publication dates, descriptions, keywords, category, live/private/unlisted state and other values exposed by YouTube.js are not authoritative through this capability. Any complete-stage requirement containing an unsupported field remains on the established yt-dlp path rather than being partially widened to values whose semantics have not been accepted.

Production acquisition sends the complete requested batch through one Node bridge process and one Innertube session. A whole-operation failure or omitted individual entry falls back to yt-dlp. Requested record order is preserved. Successful specialised rows carry explicit provider and operation provenance and are not written into the existing detailed metadata cache because that cache represents richer yt-dlp-style records.

Static explain output presents this capability as conditional physical lowering because extractor-family evidence is generally available only at runtime. Runtime provenance reports specialised provider/operation counts only where the acquired row carries explicit attribution; untagged rows remain unattributed rather than being guessed to originate from yt-dlp or cache.

## ytmusicapi specialised capability

The production ytmusicapi capability uses anonymous `YTMusic.get_song()` acquisition and is authoritative only for the same closed scalar set: `id`, `title`, `channel_id`, `duration` and `view_count`. Publication dates, descriptions, keywords, category, live/playability state, `musicVideoType` and `YTMusic.get_song_credits()` remain outside its authority.

Eligibility requires resolved YouTube source identity plus the independently established `music` source trait. Ordinary YouTube resolution is insufficient. Browser authentication is not part of this capability.

For an independently confirmed music source, the current specialised acquisition order for the shared five-field requirement is YouTube.js, then ytmusicapi, then yt-dlp. Each later provider receives only IDs still unresolved after the preceding provider. Unexpected IDs and duplicate records are ignored rather than overwriting an earlier authoritative result. This prevents provider order or relative cost from becoming an implicit disagreement-resolution policy.

Successful ytmusicapi rows carry explicit provider and `YTMusic.get_song` provenance and are not written into the full detailed metadata cache. A failed or omitted entry falls through to the remaining acquisition path without widening ytmusicapi's authority.

## Fallback and disagreement boundaries

The existing yt-dlp detailed path remains the general authoritative fallback. It already performs source-scoped bulk cache lookup, passes known video IDs to one yt-dlp process per semantic acquisition batch and preserves LIMIT-aware bounded acquisition where query semantics permit early termination.

Mixed acquisition is valid only where every provider contribution has an explicit authority and provenance contract. Cost rank, provider order and successful acquisition do not establish semantic authority. Discover does not race providers or acquire duplicate authoritative values merely to manufacture a disagreement. If a future requirement introduces genuine authoritative disagreement, its resolution policy must be designed explicitly rather than emerging from overwrite order.

General automatic multi-backend scheduling, speculative parallel acquisition and official platform developer APIs are not part of the current provider contract. They require separate evidence and design if future requirements justify them.
