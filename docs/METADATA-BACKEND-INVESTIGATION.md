# Metadata backend investigation

## Purpose

This document records the revised Phase 4 investigation for issue #81. It evaluates whether Discover can satisfy selected acquisition requirements more cheaply or reliably through multiple independent provider capabilities rather than treating one backend as the owner of an entire query.

The governing principle is requirement-oriented acquisition. A provider is useful when it can satisfy a specific semantic requirement with the required authority and provenance at an advantageous cost. It does not need to replace yt-dlp or YouTube.js wholesale.

Discover should not require Google or YouTube developer API credentials, OAuth applications or direct integration with the official YouTube Data API for ordinary metadata acquisition. User-supplied cookies remain supported where an independent acquisition tool can use them to access material the user is entitled to access. Cookies are an authentication input, not a reason to bind Discover to a platform developer API.

## Evaluation model

Future acquisition planning should distinguish five concepts:

1. the logical source expression supplied to yt-sql;
2. backend source resolution, including the provider and extractor identity where exposed;
3. semantic acquisition requirements produced by the planner;
4. provider capabilities capable of satisfying each requirement;
5. the physical provider selection used for each requirement.

This permits one query to use more than one provider without changing yt-sql semantics. A provider must not be selected merely because it exposes a similarly named field. Its value must satisfy Discover's semantic authority, provenance, boundedness and failure requirements.

Provider diversity should reduce dependence on the limitations of any one extraction implementation. It must not make results depend unpredictably on whichever provider responds first.

## Provider policy

The investigation applies the following project policy:

- do not require Google or YouTube developer API keys, OAuth applications or official developer-platform quota;
- retain optional user-supplied cookies where supported by an independent tool;
- prefer independently maintained extraction libraries and protocols that operate against public web or internal-client interfaces;
- do not use a provider merely because it is lightweight if its values cannot satisfy yt-sql's semantic contract;
- do not introduce mechanisms intended to bypass access controls;
- keep platform-specific acquisition behind the backend boundary rather than exposing it through yt-sql syntax;
- retain provider and acquisition provenance sufficiently to explain how authoritative values were obtained.

The official YouTube Data API was considered during the initial investigation and is rejected as a Discover provider under this policy. Its batching properties are attractive, but the required developer-platform relationship, credentials and quota model are not a desirable dependency for this project.

## Relative acquisition-cost scale

The estimates below are architectural estimates, not benchmark results. Phase 4 does not claim measured performance for providers that have not yet been integrated.

- **Very light**: one small remote JSON request or equivalent client operation for a known item, with little local processing and no media-format extraction.
- **Light**: narrow per-item metadata acquisition with limited parsing and no need to construct the complete media information model.
- **Medium**: per-item extraction that may parse substantial player/page state, perform several internal requests or return stream information beyond the scalar fields required by the query.
- **Heavy**: broad detailed extraction comparable to the current complete yt-dlp information path.
- **Client-light / server-variable**: Discover makes a small request to a third-party or self-hosted service, but the service performs the actual extraction and therefore moves rather than eliminates acquisition cost.

Actual provider selection must eventually use measurements rather than these labels.

## Current yt-dlp path

The Phase 3 audit established that the detailed path already sends a known set of video URLs through one yt-dlp process invocation and performs cache filtering before that work. The main cost is authoritative per-video extraction, not repeated process startup.

yt-dlp remains the broadest provider in the current architecture. It exposes a rich information dictionary, supports many services and can use cookies where required. Its extractor registry is ordered and the first suitable extractor handles a URL, with the generic extractor retained as a fallback. URL appearance alone is therefore not a reliable provider classification.

The current Discover lowering has only two useful yt-dlp acquisition granularities: flat enumeration and complete detailed JSON. Formats, subtitles, chapters, thumbnails, tags, categories and dynamic raw metadata remain separate semantic stages in the backend-neutral plan but collapse to complete extraction in the yt-dlp adapter.

No supported yt-dlp interface identified by this investigation provides a general bulk endpoint for exact scalar metadata that avoids the underlying per-item extractor work. The existing detailed path should remain the broad compatibility baseline for requirements that cannot be satisfied more narrowly elsewhere.

**Potential metadata:** essentially the full current Discover detailed metadata surface, subject to extractor support.

**Estimated acquisition weight:** heavy for scalar-only requirements, but appropriate when richer extraction is actually required.

## YouTube.js / youtubei.js

YouTube.js is already part of Discover's efficient YouTube collection-enumeration path. It is an independent JavaScript client for YouTube's internal Innertube API and does not require the official developer API.

Its `getBasicInfo()` and `getInfo()` methods provide per-video information, while `resolveURL()` can resolve a YouTube URL to an Innertube navigation endpoint. `getBasicInfo()` is the most interesting existing candidate for narrower scalar metadata because it avoids deliberately requesting the broader `getInfo()` model.

No bulk known-video-ID metadata interface was identified in the reviewed API. It should therefore be treated as per-video acquisition unless later investigation discovers a supported batching mechanism.

**Potential metadata:** title and video identity, channel/uploader information, duration and view-related/player metadata, thumbnails, playback/player information and other Innertube video details. Exact field authority must be established from actual returned structures rather than inferred from similarly named values.

**Estimated acquisition weight:** light to medium per video. Likely substantially narrower than complete yt-dlp extraction for scalar-only requirements, but still network work per candidate.

**Best next use:** benchmark `getBasicInfo()` against the exact scalar fields that currently trigger detailed yt-dlp extraction. It is especially attractive because Discover already has the runtime and integration boundary.

## youtube-innertube

`youtube-innertube` is a small independent Python library that talks directly to Innertube without an API key, OAuth or third-party dependencies. Its documented `video_details()` result includes title, description, channel identity, view count, duration, keywords, thumbnails, publish date, category, live status and available caption languages.

The project explicitly describes itself as pure Python standard library code with no dependencies. It also documents the operational realities of Innertube, including changing renderers, client fallback and IP-based rate limiting.

This makes it an unusually interesting research candidate for Discover because integration overhead would be small and the returned field set overlaps closely with the scalar metadata identified in Phase 3. Its maturity, maintenance history, behaviour under cookies/authentication and semantic consistency across difficult videos need much more scrutiny before it could become an authoritative provider.

**Potential metadata:** title, description, channel/channel ID, view count, duration, keywords/tags-like data, thumbnails, publish date, category, live state and caption-language availability.

**Estimated acquisition weight:** very light to light per video for the documented scalar path. No bulk known-ID endpoint is documented, so cost still scales with candidates.

**Best next use:** prototype only. Compare its raw responses and normalised fields against yt-dlp and YouTube.js over the deterministic provider corpus before considering production integration.

## pytubefix

pytubefix is an independent Python YouTube extraction library with no third-party dependencies. Its documented feature surface includes streams, captions, playlists, channels, chapters, thumbnails, authentication support and related video information. Real-world usage and project issues demonstrate properties including title, author, views, channel identity, description, duration, keywords and publish date.

Its Python-native integration is attractive, but it performs full per-video object extraction and has experienced bot-detection and changing-response issues, as expected for a YouTube extractor. It should not be assumed to be cheaper than YouTube.js `getBasicInfo()` merely because it runs in-process.

**Potential metadata:** title, author/channel, views, duration, publish date, description, keywords, thumbnails, chapters, captions, age-restriction information and stream metadata.

**Estimated acquisition weight:** light to medium for basic metadata, potentially medium or heavier when stream/player information is initialised. Per-video rather than bulk.

**Best next use:** comparative prototype if YouTube.js basic information does not cover enough exact fields or if a Python-native fallback materially improves resilience.

## NewPipeExtractor

NewPipeExtractor is an established independent extraction engine used by NewPipe and Piped. For services where official APIs are restricted or proprietary, NewPipe documents that it parses the website or uses internal APIs instead. It supports YouTube as well as other services and exposes general video information, descriptions, tags, streams, subtitles, channels, playlists and search.

Its recent release history shows active maintenance around YouTube duration, date and view extraction. That is positive for resilience, but also demonstrates that lightweight listing metadata can be structurally unstable and sometimes approximate. NewPipe's own issue history records cases where Shorts listing views are not exact.

The principal integration cost for Discover is architectural: NewPipeExtractor is Java/Kotlin ecosystem software rather than a native Python dependency. Calling it locally would add a runtime/process boundary or require a service wrapper.

**Potential metadata:** title, uploader/channel, duration, views, upload date, description, tags, streams, subtitles, related items, playlist/channel/search metadata and service identity.

**Estimated acquisition weight:** medium locally for full stream information; potentially light for item/listing extractors where their authority is sufficient. Integration/runtime weight is high relative to Python or the already-present YouTube.js runtime.

**Best next use:** treat as a diversity candidate and semantic cross-check, not an immediate dependency. Investigate only if it exposes a narrow metadata path that materially outperforms existing providers or broadens non-YouTube coverage.

## Invidious API

Invidious exposes an unauthenticated JSON API. Its `/api/v1/videos/:id` schema includes title, video ID, thumbnails, description, view count, duration, publication information and additional video information. It can therefore satisfy many of the scalar requirements relevant to Discover.

From Discover's process this is extremely lightweight: one ordinary JSON request can return a normalised video object. The important caveat is that the extraction work is performed by the selected Invidious instance. Using a public instance shifts acquisition cost, availability, privacy and trust to a third party. A self-hosted instance avoids that trust transfer but is a substantial deployment dependency.

Invidious should therefore not become a mandatory provider or silent default. It could be useful as an explicitly configured optional provider, particularly for experimentation and resilience.

**Potential metadata:** title, video ID, author/channel information, description, view count, duration, publication time/text, thumbnails and broader video information depending on the endpoint.

**Estimated acquisition weight:** client-light / server-variable. Very light for Discover itself, but not intrinsically cheap end to end.

**Issue #110 outcome:** retain only as experimental explicitly configured infrastructure. Four selected public deployments failed the required video capability through a TLS handshake timeout or HTTP 403 responses, including an explicitly disabled endpoint. This is operational evidence rather than a semantic verdict because no successful public-instance comparison corpus was obtained. Do not add automatic public-instance discovery or fallback.

## Piped API

Piped is an independent privacy-oriented frontend whose backend uses NewPipeExtractor and does not use the official YouTube API. Its unauthenticated `/streams/{videoId}` endpoint returns a rich `VideoInfo` object including title, description, duration, upload date, uploader information, views, category, tags, subtitles and stream information. Channel and listing objects also expose duration, title, upload information, uploader and views.

As with Invidious, a Piped HTTP provider would be very lightweight from Discover's process while moving the extraction work to the configured instance. Public-instance reliability and trust therefore matter, and self-hosting introduces operational weight. The endpoint is also richer than necessary for a scalar-only query because it includes stream information.

**Potential metadata:** title, description, duration, upload date, uploader/channel information, views, category, tags, subtitles, thumbnails and stream information.

**Estimated acquisition weight:** client-light / server-variable. The `/streams` response is broader than a scalar-only requirement, so network payload and server work may be medium even though client integration is simple.

**Best next use:** optional configured-provider experiment, especially as a comparison against direct NewPipeExtractor integration. Do not treat arbitrary public instances as trusted infrastructure.

## ytmusicapi

ytmusicapi is an independent Python client for YouTube Music's internal web API. It can use user cookie data for authentication and supports search, artist/releases, albums, song metadata, playlists, podcasts and library operations.

It is intentionally specialised. It should not become a general YouTube video metadata provider, but it may eventually offer cheaper or richer acquisition for sources that have been reliably resolved as YouTube Music and whose yt-sql requirements map to its documented data.

**Potential metadata:** music-specific song/video identity and metadata, artists, albums, releases, playlists and related YouTube Music structures.

**Estimated acquisition weight:** light for the specialised metadata it exposes, but unsuitable for general video acquisition.

**Best next use:** defer until source-resolution and capability selection can prove that a query is operating on a YouTube Music source. It is a good example of why provider selection should be requirement and source aware.

## FreeTube

FreeTube is relevant primarily as architectural evidence rather than as a new provider dependency. Its current local API uses YouTube.js, and it can alternatively use Invidious. It explicitly avoids official APIs.

Discover would gain little from integrating FreeTube itself because the useful acquisition mechanisms underneath it are already represented directly by YouTube.js and Invidious. Its architecture nevertheless supports the project's direction: multiple independent acquisition paths can coexist behind one application without changing the user's query model.

**Estimated acquisition weight:** not separately applicable. Prefer the underlying provider directly.

## Candidate comparison

| Candidate | Useful field families | Acquisition shape | Relative weight | Cookies/auth | Main concern |
| --- | --- | --- | --- | --- | --- |
| yt-dlp | Broadest metadata, formats and extractor-specific data | Per-item extraction within existing bulk invocation | Heavy for scalar-only work | Strong existing cookie support | More work than narrow scalar queries require |
| YouTube.js `getBasicInfo()` | Promising scalar/player metadata | Per video | Light-medium | Session/auth capabilities require focused audit | Exact authority must be proven field by field |
| `youtube-innertube` | Scalar video metadata, category, keywords, live/caption state | Per video | Very light-light | Authentication/cookie capability needs audit | Younger/smaller dependency and Innertube churn |
| pytubefix | Broad video metadata, chapters, captions and streams | Per video | Light-medium | Supports authentication mechanisms | May duplicate substantial extraction work and encounter bot detection |
| NewPipeExtractor | Broad cross-service metadata and streams | Per item / listing | Medium, with heavier integration | Service-dependent | Java runtime/integration cost and some approximate listing fields |
| Invidious API | Normalised video scalar metadata and more | One HTTP request per video endpoint | Client-light / server-variable | Instance-dependent | Third-party instance trust/reliability or self-hosting burden |
| Piped API | Rich video metadata, subtitles and streams | One HTTP request per video endpoint | Client-light / server-variable | Instance-dependent | Rich endpoint may do more work than scalar query needs |
| ytmusicapi | YouTube Music metadata | Specialised requests | Light | Optional user cookies | Music-only semantic scope |

None of these estimates substitutes for measurement. The most promising immediate local candidates are YouTube.js `getBasicInfo()` because it is already integrated, and `youtube-innertube` because its documented scalar surface is narrow and Python-native. pytubefix is a reasonable diversity candidate. NewPipeExtractor is attractive for provider diversity and cross-service experience but has greater integration cost. Invidious and Piped are potentially cheap from the client perspective but introduce an explicit service-instance trust and reliability boundary.

## Cookies and authenticated acquisition

The absence of official developer credentials does not imply anonymous-only acquisition.

Discover may continue to accept user-supplied cookies and pass them to providers that have a clear, supported authentication mechanism. Provider capabilities should declare whether they support anonymous acquisition, cookie-authenticated acquisition or both. A provider that cannot consume the user's authentication context must not silently replace one that is required to access the requested material.

Cookies remain sensitive runtime material. They must not be written into caches, explain output, logs, profiles or release artefacts. Provider selection should expose that authentication was required or available without exposing credential contents.

## Provider diversity and authority

A future provider contract should describe at least:

- semantic stages and fields it can satisfy;
- whether each value is exact, approximate or unavailable;
- supported source/platform identities;
- useful request granularity and whether any batching exists;
- anonymous and cookie-authenticated capabilities;
- rate-limiting characteristics known to the integration;
- cache/provenance identity;
- failure and partial-result semantics;
- relative acquisition cost based on measurements;
- whether capability selection is deterministic and explainable.

If two providers can authoritatively satisfy the same requirement, provider selection must be deterministic and explainable. Discover should retain sufficient provenance to diagnose disagreements rather than silently accepting whichever provider responds first.

Provider disagreement should initially be treated as diagnostic evidence, not an invitation to vote values together. The semantic contract for reconciliation requires separate design work.

## Source resolution as planner evidence

Source resolution is relevant both to diagnostics and to provider eligibility. yt-dlp's extractor system chooses an information extractor for a URL, and extracted information dictionaries expose extractor identity fields such as `extractor` and `extractor_key`. Discover already recognises those names as metadata during query evaluation, but does not currently promote them into a resolved-source planning contract.

This information should be exposed when it is available. A useful diagnostic model distinguishes:

- requested source expression;
- resolution provider;
- raw backend extractor identity;
- platform/service identity, only where it can be derived reliably;
- source kind, only where explicitly supported rather than guessed;
- Discover's logical source/facet identity.

The raw extractor identity is provenance. It is not automatically a stable semantic source kind. A generic extractor can match arbitrary URLs and may discover embedded media from another service. yt-dlp's generic fallback also means a reliable pre-extraction supported/unsupported URL test cannot be based solely on URL matching.

Where extractor selection can be obtained before expensive acquisition through a supported or sufficiently stable interface, it may constrain provider eligibility. A YouTube-only metadata provider must not be scheduled for a source that yt-dlp has resolved to an unrelated platform. If a future explicit source/platform constraint disagrees with backend resolution, Discover should surface the disagreement rather than silently choosing one interpretation.

If reliable resolution is available only after extraction has already performed substantial work, it remains useful provenance and diagnostics but has less value as a pre-acquisition planning primitive. This timing distinction needs a dedicated implementation investigation.

## Revised recommended direction

Do not replace the existing backends as part of issue #81. The revised investigation supports these follow-up directions:

1. introduce a provider-capability model that can map one semantic requirement to multiple eligible independent providers without changing the logical plan;
2. expose and retain backend source/extractor resolution, then determine which resolution facts are sufficiently stable to constrain provider selection;
3. use resolved source identity to prevent platform-specific providers from being scheduled for unrelated sources;
4. benchmark YouTube.js `getBasicInfo()` as the first narrow provider candidate because its runtime is already present;
5. prototype `youtube-innertube` against the scalar requirement corpus and assess its maintenance and authentication characteristics;
6. compare pytubefix where it can provide a genuinely independent acquisition path rather than duplicating yt-dlp at similar cost;
7. investigate NewPipeExtractor, Invidious and Piped as optional diversity paths while accounting explicitly for runtime or instance trust boundaries;
8. defer specialised providers such as ytmusicapi until source resolution can prove their semantic applicability.

The existing yt-dlp and YouTube.js paths remain accepted behaviour until a candidate demonstrates both semantic correctness and an operational advantage. Official Google/YouTube developer APIs are outside the intended provider set. User-supplied cookies remain an available authentication mechanism where the selected independent provider supports them.

## External references reviewed

- yt-dlp README and metadata fields: https://github.com/yt-dlp/yt-dlp/blob/master/README.md
- yt-dlp extractor contract: https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/common.py
- YouTube.js repository: https://github.com/LuanRT/YouTube.js
- YouTube.js Innertube implementation: https://github.com/LuanRT/YouTube.js/blob/main/src/Innertube.ts
- youtube-innertube repository: https://github.com/danielvangulla/youtube-innertube
- pytubefix documentation: https://github.com/JuanBindez/pytubefix/blob/main/docs/index.rst
- NewPipeExtractor repository and releases: https://github.com/TeamNewPipe/NewPipeExtractor
- Invidious API documentation: https://docs.invidious.io/api/
- Piped API documentation: https://docs.piped.video/docs/api-documentation/
- Piped OpenAPI specification: https://github.com/TeamPiped/OpenAPI/blob/main/swagger.yaml
- ytmusicapi repository: https://github.com/sigma67/ytmusicapi
- FreeTube repository: https://github.com/FreeTubeApp/FreeTube
