# Metadata provider benchmark

## Purpose

Issues #102, #103, #104 and #109 evaluate lightweight known-video metadata acquisition without changing Discover's production acquisition planner. The shared benchmark compares experimental YouTube.js `getBasicInfo()`, `youtube-innertube`, pytubefix and NewPipeExtractor acquisition against the existing yt-dlp detailed path over the same corpus.

The benchmark is evidence gathering. A field being present, or even equal to yt-dlp in one run, does not establish authoritative semantic equivalence.

## Providers

The harness supports `youtubejs`, `youtube-innertube`, `pytubefix`, `newpipe-extractor` and `ytdlp`. yt-dlp is always included as the comparison reference. YouTube.js uses Discover's existing Node.js bridge and reuses one Innertube session for the corpus. `youtube-innertube` calls its Python `video_details()` path once per known video ID. pytubefix constructs a `YouTube` object for each known video and records the acquisition cost of resolving the benchmark metadata surface.

`youtube-innertube` is deliberately an optional benchmark dependency rather than a production Discover dependency. Install the research candidate directly from its upstream repository before running that provider:

```bash
python -m pip install git+https://github.com/danielvangulla/youtube-innertube
```

Pytubefix is likewise an optional research dependency for issue #104 rather than a production Discover dependency:

```bash
python -m pip install pytubefix
```

NewPipeExtractor is an issue #109 research candidate and remains outside production Discover acquisition. Its JVM bridge pins NewPipeExtractor v0.26.5. Build the bridge once before benchmarking it:

```bash
cd tools/newpipe-extractor-bridge
gradle installDist
```

The benchmark discovers the installed launcher automatically. `YT_DISCOVER_NEWPIPE_BRIDGE` may name an alternative launcher path. The bridge keeps one JVM process alive for the complete corpus and records both per-item extraction time and residual process startup/shutdown time. This avoids conflating a deliberately inefficient one-JVM-per-video design with NewPipeExtractor's extraction cost.

## Measurement profiles

Benchmark schema 8 defines provider-neutral measurement profiles so elapsed times are compared only when providers are asked to satisfy the same acquisition contract. The default `core` profile requests only the established scalar metadata and provider-native availability or live-state source signals. Extended thumbnail, chapter and caption probing is not performed in this profile. This makes the ordinary four-provider timing comparison directly comparable and avoids charging one provider for optional capability work that the others were not asked to perform.

The `full` profile independently measures acquisition of the core surface plus the structural extended-capability inventory. It is currently supported by pytubefix and yt-dlp. YouTube.js, youtube-innertube and NewPipeExtractor are explicitly marked as core-only rather than silently treating unsupported extended capabilities as zero-cost. A full-profile run should therefore name only providers that support it, for example `--providers pytubefix,ytdlp --profile full`. Each profile is a fresh benchmark invocation; incremental costs may be derived by comparing repeated core and full runs, but the harness does not infer per-property network costs from access order or provider caching.

The report records the selected `measurement_profile` and the declared `profile_support` matrix. Unsupported profiles fail explicitly. This is intentional: benchmark timing must describe work actually requested from a provider rather than mixing unlike acquisition surfaces.

## Running the benchmark

For all providers:

```bash
python scripts/benchmark_metadata_providers.py --json -- VIDEO_ID [VIDEO_ID ...]
```

For IDs stored one per line, use the end-of-options marker because a valid YouTube video ID may begin with `-`:

```bash
python scripts/benchmark_metadata_providers.py --json -- $(cat ./ids/ids-curiousmarc-bench) > bench.json
```

To benchmark only the #103 candidate against yt-dlp:

```bash
python scripts/benchmark_metadata_providers.py --providers youtube-innertube --json -- $(cat ./ids/ids-curiousmarc-bench) > bench-103.json
```

To benchmark the #104 pytubefix candidate against yt-dlp:

```bash
python scripts/benchmark_metadata_providers.py --providers pytubefix --profile core --json -- $(cat ./ids/ids-curiousmarc-bench) > bench-104-core.json

python scripts/benchmark_metadata_providers.py --providers pytubefix,ytdlp --profile full --json -- $(cat ./ids/ids-curiousmarc-bench) > bench-104-full.json
```

To benchmark the #109 NewPipeExtractor candidate against yt-dlp:

```bash
python scripts/benchmark_metadata_providers.py --providers newpipe-extractor --profile core --json -- $(cat ./ids/ids-curiousmarc-bench) > bench-109.json
```

Add `--debug-external` when the JVM bridge invocation should be shown on stderr through the shared external-tool diagnostics.

The older #102-specific harness remains available so retained #102 evidence and its schema stay reproducible.

## Comparison surface

The shared normalised comparison covers `id`, `title`, `description`, `channel_id`, `duration`, `view_count`, `upload_date`, `category`, `is_live` and `keywords`. Each value is classified as equal, different or missing relative to yt-dlp.

Some comparisons require semantic interpretation rather than literal promotion. In particular, `youtube-innertube`'s `publishDate` and pytubefix's `publish_date` must not automatically become Discover's authoritative `upload_date`; provider keywords must not automatically become authoritative yt-dlp-style tags; category and live-state representation may differ; and mutable values such as view counts can legitimately change between sequential provider requests.

For differing `view_count` values, the machine-readable comparison also records the candidate value, yt-dlp reference value, signed absolute delta and relative percentage delta. View counts are mutable and provider surfaces may update at different times, so the delta is evidence for interpretation rather than an automatic semantic failure. Equal or unavailable counts do not emit a delta.

## Pytubefix extended capability inventory

Issue #104 also asks whether pytubefix exposes useful metadata outside the established scalar comparison surface. Successful pytubefix rows in the `full` profile therefore contain an `extended_capabilities` inventory for thumbnail availability, chapters and captions. The inventory records availability and small structural facts such as counts or caption codes, not thumbnail URLs, chapter text or caption content. Capability probing is deliberately separate from scalar normalisation so a failure while inspecting chapters or captions does not discard otherwise valid core metadata.

The inventory is evidence only. A property being present does not establish its authority, acquisition cost or suitability for Discover. In particular, pytubefix `videoDetails.isLiveContent` is retained as a provider-native source signal and is not mapped directly to Discover's current `is_live` semantic. Publication dates are normalised to `YYYYMMDD` for comparison when pytubefix supplies a date, but equality with yt-dlp remains something the corpus must establish rather than an assumption in the adapter.

Pytubefix per-video elapsed time is retained so the corpus can expose expensive individual acquisitions. Exact request counts and transferred bytes are currently reported as not instrumented rather than inferred from implementation details. If #104 demonstrates a reason to pursue pytubefix further, request-level instrumentation can be added without changing the normalised semantic surface.

## Cookie-authenticated YouTube.js comparison

The benchmark can optionally run a second YouTube.js variant with user-supplied cookie authentication while preserving the ordinary anonymous YouTube.js run over the same corpus. Prefer `--youtubejs-cookies FILE` with a Netscape-format cookie file, matching Discover's existing `--cookies FILE` input. The harness applies normal domain, path, secure and expiry rules, constructs the HTTP `Cookie` header required by YouTube.js internally, and passes it only through the child-process environment. The lower-level `--youtubejs-cookie` switch remains available for a complete Cookie request-header value supplied through `YT_DISCOVER_YOUTUBEJS_COOKIE`. The two authentication inputs are mutually exclusive.

```console
python scripts/benchmark_metadata_providers.py --youtubejs-cookies /path/to/cookies.txt --json -- $(cat ./ids/ids-adversarial-bench) > bench-authenticated.json
```

The report labels the variants as `youtubejs` and `youtubejs-cookie`, compares both against yt-dlp, and records `youtubejs-cookie-against-anonymous` under `variant_comparisons`. Anonymous YouTube.js explicitly removes any inherited benchmark cookie from its child environment so the two variants remain distinct. Third-party diagnostics are redacted before they enter the report, and serialisation fails closed if the constructed header or applicable cookie values remain anywhere in the payload. Cookie contents, derived credential material and credential metadata must not be written to benchmark output.

Discover's existing Netscape `--cookies FILE` input is also forwarded to the production YouTube.js channel-enumeration adapter when that backend is selected. Translation into the provider-specific HTTP header occurs at the adapter boundary. The authentication context therefore follows the acquisition request without becoming yt-sql semantics, planner metadata, provenance or command-line subprocess arguments.

Machine-readable schema version 8 records the selected measurement profile and provider support matrix and retains normalised rows, provider elapsed time, per-video `youtube-innertube` elapsed time, provider success/failure summaries and structured acquisition failures. Successful rows also retain a deliberately small `source_signals` diagnostic object: YouTube.js exposes its playability/private/live flags, yt-dlp exposes its live-history and availability fields, and `youtube-innertube` exposes its `isLive` value plus the names of keys returned by `video_details()`. These diagnostics are evidence only and are not part of the normalised semantic comparison surface. A failed video does not abort an adversarial benchmark: comparisons distinguish candidate failure, reference failure and failure on both sides. yt-dlp runs the corpus in one process with `--ignore-errors`; its standard error is captured rather than leaked into JSON-oriented terminal output, and per-video diagnostics are retained where yt-dlp identifies the affected video. Exact transferred network bytes are not claimed because neither existing provider boundary exposes a trustworthy common measurement without additional instrumentation.

## Corpus and failure testing

Use the same recorded corpus when comparing #102 and #103. Include ordinary videos and, as the investigation expands, Shorts, active and completed livestreams, scheduled content, unavailable content and other unusual classes. Expected acquisition failures are benchmark evidence and remain in the final report as classified failures such as `private`, `removed`, `rate_limited`, `authentication_required`, `unavailable` or the conservative fallback `provider_error`; the original diagnostic message is preserved. Repeat performance runs rather than treating one wall-clock measurement as stable because network conditions and YouTube throttling vary. For the final #103 validation, repeat the adversarial corpus three times to observe classification stability and transient throttling, and include a video confirmed to be actively live at the time of the run when practical.

Authentication remains provider-specific. The benchmark can compare YouTube.js anonymously and with user-supplied cookies as described above. Upstream `youtube-innertube` currently describes itself as unauthenticated and states that it does not access private or age-gated content. Do not invent a cookie bridge around that limitation merely to satisfy the benchmark. Record the limitation as part of the provider assessment and keep credentials out of benchmark output and fixtures.

## Upstream reliability observations

At the time of issue #103, the upstream `youtube-innertube` repository is very small and young. Its own documentation explicitly warns that Innertube renderer names change without notice, that client fallback is needed when a client is throttled, and that YouTube rate-limits by IP. Those are relevant reliability characteristics rather than reasons to reject the experiment prematurely.

The upstream project is pure standard-library Python and documents no third-party runtime dependencies. That gives it a small integration footprint, but its limited history means Discover should require substantially more live evidence before treating it as an authoritative production provider.

## YouTube.js diagnostic boundary

Normal Discover operation filters the known YouTube.js `Text` attachment-run parser warning that was reproduced while enumerating the CuriousMarc corpus. The filter is deliberately narrow: it does not redirect Node.js standard error, does not suppress `console.error`, and does not change bridge failure reporting. Set `YT_DISCOVER_YOUTUBEJS_DIAGNOSTICS=1` when investigating third-party parser behaviour to leave the warning visible. The CuriousMarc benchmark remains the compatibility check for confirming that this presentation-parser warning does not correspond to metadata loss in the fields under comparison.

## Promotion boundary

Issues #103 and #104 do not register `youtube-innertube` or pytubefix capabilities with Discover and do not alter automatic acquisition planning. Promotion requires a later field-by-field authority decision based on repeated corpus evidence, difficult-content behaviour, failure characteristics, maintenance risk and a clear authentication policy.

## Issue #109 heterogeneous variation

After the single-channel CuriousMarc run, use the checked-in heterogeneous corpus to exercise materially different source shapes before drawing a production-integration conclusion. The corpus records sampling intentions rather than expected provider answers so live service changes do not silently become test assertions.

Run the NewPipeExtractor variation from the repository root with:

```bash
python scripts/benchmark_metadata_providers.py --providers newpipe-extractor --profile core --json -- $(python -c 'import json; print(" ".join(item["id"] for item in json.load(open("benchmarks/metadata-provider-corpora/issue-109-heterogeneous.json"))["items"]))') > bench-109-heterogeneous.json
```

Schema version 9 adds `description_analysis` to successful comparisons. Raw description equality remains unchanged. The additional analysis strips provider-specific HTML markup, decodes entities, collapses whitespace and reports a similarity ratio. Similarity is evidence only and must not be interpreted as semantic authority or automatic equivalence, particularly where one provider abbreviates visible link text while another exposes a complete URL.

The heterogeneous corpus includes old and newer material, different channels, music and non-English metadata, short-form candidates, historical live-stream pages and other source shapes. Traits are intentionally descriptive sampling goals rather than assertions about the current state of mutable YouTube resources.
