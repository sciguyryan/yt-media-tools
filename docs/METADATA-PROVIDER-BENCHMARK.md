# Metadata provider benchmark

## Purpose

Issues #102 and #103 evaluate lightweight known-video metadata acquisition without changing Discover's production acquisition planner. The shared benchmark compares experimental YouTube.js `getBasicInfo()` and `youtube-innertube` acquisition against the existing yt-dlp detailed path over the same corpus.

The benchmark is evidence gathering. A field being present, or even equal to yt-dlp in one run, does not establish authoritative semantic equivalence.

## Providers

The harness supports `youtubejs`, `youtube-innertube` and `ytdlp`. yt-dlp is always included as the comparison reference. YouTube.js uses Discover's existing Node.js bridge and reuses one Innertube session for the corpus. `youtube-innertube` calls its Python `video_details()` path once per known video ID.

`youtube-innertube` is deliberately an optional benchmark dependency rather than a production Discover dependency. Install the research candidate directly from its upstream repository before running that provider:

```bash
python -m pip install git+https://github.com/danielvangulla/youtube-innertube
```

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

The older #102-specific harness remains available so retained #102 evidence and its schema stay reproducible.

## Comparison surface

The shared normalised comparison covers `id`, `title`, `description`, `channel_id`, `duration`, `view_count`, `upload_date`, `category`, `is_live` and `keywords`. Each value is classified as equal, different or missing relative to yt-dlp.

Some comparisons require semantic interpretation rather than literal promotion. In particular, `youtube-innertube`'s `publishDate` must not automatically become Discover's authoritative `upload_date`; `keywords` must not automatically become authoritative yt-dlp-style tags; category representation may differ; and mutable values such as view counts can legitimately change between sequential provider requests.

For differing `view_count` values, the machine-readable comparison also records the candidate value, yt-dlp reference value, signed absolute delta and relative percentage delta. View counts are mutable and provider surfaces may update at different times, so the delta is evidence for interpretation rather than an automatic semantic failure. Equal or unavailable counts do not emit a delta.

## Cookie-authenticated YouTube.js comparison

The benchmark can optionally run a second YouTube.js variant with user-supplied cookie authentication while preserving the ordinary anonymous YouTube.js run over the same corpus. Set `YT_DISCOVER_YOUTUBEJS_COOKIE` to the complete Cookie request-header value and pass `--youtubejs-cookie`. The cookie is inherited by the YouTube.js bridge only through the child-process environment; it is never placed in subprocess arguments or benchmark output. The report labels the variants as `youtubejs` and `youtubejs-cookie`, compares both against yt-dlp, and also records `youtubejs-cookie-against-anonymous` under `variant_comparisons`.

```console
YT_DISCOVER_YOUTUBEJS_COOKIE='...' python scripts/benchmark_metadata_providers.py --youtubejs-cookie --json -- $(cat ./ids/ids-adversarial-bench) > bench-authenticated.json
```

The cookie option fails if the environment variable is absent or empty. Anonymous YouTube.js explicitly removes any inherited benchmark cookie from its child environment so the two variants remain distinct. Before serialising a report, the harness fails closed if the supplied cookie value appears anywhere in the report payload. Cookie authentication remains experimental benchmark infrastructure and does not change Discover's production acquisition or authentication behaviour.

Machine-readable schema version 5 retains normalised rows, provider elapsed time, per-video `youtube-innertube` elapsed time, provider success/failure summaries and structured acquisition failures. Successful rows also retain a deliberately small `source_signals` diagnostic object: YouTube.js exposes its playability/private/live flags, yt-dlp exposes its live-history and availability fields, and `youtube-innertube` exposes its `isLive` value plus the names of keys returned by `video_details()`. These diagnostics are evidence only and are not part of the normalised semantic comparison surface. A failed video does not abort an adversarial benchmark: comparisons distinguish candidate failure, reference failure and failure on both sides. yt-dlp runs the corpus in one process with `--ignore-errors`; its standard error is captured rather than leaked into JSON-oriented terminal output, and per-video diagnostics are retained where yt-dlp identifies the affected video. Exact transferred network bytes are not claimed because neither existing provider boundary exposes a trustworthy common measurement without additional instrumentation.

## Corpus and failure testing

Use the same recorded corpus when comparing #102 and #103. Include ordinary videos and, as the investigation expands, Shorts, active and completed livestreams, scheduled content, unavailable content and other unusual classes. Expected acquisition failures are benchmark evidence and remain in the final report as classified failures such as `private`, `removed`, `rate_limited`, `authentication_required`, `unavailable` or the conservative fallback `provider_error`; the original diagnostic message is preserved. Repeat performance runs rather than treating one wall-clock measurement as stable because network conditions and YouTube throttling vary. For the final #103 validation, repeat the adversarial corpus three times to observe classification stability and transient throttling, and include a video confirmed to be actively live at the time of the run when practical.

Authentication remains provider-specific. The benchmark can compare YouTube.js anonymously and with user-supplied cookies as described above. Upstream `youtube-innertube` currently describes itself as unauthenticated and states that it does not access private or age-gated content. Do not invent a cookie bridge around that limitation merely to satisfy the benchmark. Record the limitation as part of the provider assessment and keep credentials out of benchmark output and fixtures.

## Upstream reliability observations

At the time of issue #103, the upstream `youtube-innertube` repository is very small and young. Its own documentation explicitly warns that Innertube renderer names change without notice, that client fallback is needed when a client is throttled, and that YouTube rate-limits by IP. Those are relevant reliability characteristics rather than reasons to reject the experiment prematurely.

The upstream project is pure standard-library Python and documents no third-party runtime dependencies. That gives it a small integration footprint, but its limited history means Discover should require substantially more live evidence before treating it as an authoritative production provider.

## YouTube.js diagnostic boundary

Normal Discover operation filters the known YouTube.js `Text` attachment-run parser warning that was reproduced while enumerating the CuriousMarc corpus. The filter is deliberately narrow: it does not redirect Node.js standard error, does not suppress `console.error`, and does not change bridge failure reporting. Set `YT_DISCOVER_YOUTUBEJS_DIAGNOSTICS=1` when investigating third-party parser behaviour to leave the warning visible. The CuriousMarc benchmark remains the compatibility check for confirming that this presentation-parser warning does not correspond to metadata loss in the fields under comparison.

## Promotion boundary

Issue #103 does not register `youtube-innertube` capabilities with Discover and does not alter automatic acquisition planning. Promotion requires a later field-by-field authority decision based on repeated corpus evidence, difficult-content behaviour, failure characteristics, maintenance risk and a clear authentication policy.
