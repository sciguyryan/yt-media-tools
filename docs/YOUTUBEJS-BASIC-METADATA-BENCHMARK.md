# YouTube.js basic metadata benchmark

## Purpose

Issue #102 evaluates whether YouTube.js `getBasicInfo()` can satisfy a useful subset of Discover's exact per-video metadata requirements more cheaply than complete yt-dlp detailed extraction. This is an experimental benchmark only. It does not register YouTube.js as a detailed metadata provider and does not change production acquisition planning.

The existing YouTube.js dependency is reused. No official YouTube Data API, developer key or OAuth application is introduced.

## Upstream acquisition shape

YouTube.js documents `getBasicInfo(video_id)` separately from `getInfo(video_id)`. The current implementation constructs the player/watch endpoint and returns `VideoInfo`. Upstream maintainers have also described `getBasicInfo()` as requiring one request where `getInfo()` requires two when the additional metadata is unnecessary.

This makes `getBasicInfo()` a credible narrow per-video candidate, but not a bulk metadata interface. No supported known-ID batching operation was identified. Acquisition cost therefore still grows with the number of detailed candidates.

The benchmark deliberately reuses one `Innertube` session for the complete corpus so Node.js startup and session creation are not repeated for every video.

## Benchmark harness

Run:

```bash
python scripts/benchmark_youtubejs_basic_metadata.py VIDEO_ID [VIDEO_ID ...]
```

Use `--json` for a versioned machine-readable result suitable for retaining benchmark evidence.

The harness compares one YouTube.js session using `getBasicInfo()` against the existing yt-dlp detailed shape using one yt-dlp invocation over the same known video IDs. It records wall-clock time and compares the following initial scalar boundary:

- `id`;
- `title`;
- `channel_id`;
- `duration`;
- `view_count`.

YouTube.js per-item elapsed time is also retained in its raw benchmark rows. The comparison classifies each field as equal, different or missing. Equality with yt-dlp is evidence for investigation, not proof that the field has identical semantics.

## Candidate field observations

`VideoInfo.basic_info` exposes promising values for video identity, title, channel identity, duration and view count. It can also expose description, keywords and live/private/unlisted state. These are intentionally retained by the bridge so later corpus runs can investigate them without changing production metadata normalisation.

Publication date is the important current gap. `getBasicInfo()` does not establish an exact `upload_date` contract in this benchmark. Discover must therefore continue to treat exact publication date as unsatisfied unless a later investigation proves an authoritative source for it.

The benchmark also does not promote `keywords` to Discover `tags`, or any live/private flags to existing yt-sql fields. Similar naming is not sufficient semantic evidence.

## Corpus requirements

Performance conclusions must use a recorded corpus rather than a single convenient public video. At minimum the corpus should include ordinary videos, Shorts, active and completed livestreams, scheduled content where available, and unavailable content. Cookie-authenticated cases should be tested separately when the user supplies suitable cookies and the YouTube.js authentication path has been deliberately wired for the benchmark.

Do not place cookies or other credentials in benchmark output, fixtures, source files or release artefacts.

Network benchmarks are intentionally not part of the deterministic pytest suite. They depend on platform state, geography, throttling and network conditions. The checked-in tests cover benchmark structure and comparison semantics instead.

## Current conclusion

YouTube.js `getBasicInfo()` remains a strong experimental candidate for exact scalar acquisition because it is narrower than `getInfo()` and Discover already carries the runtime dependency. The current evidence is not sufficient to register it as an authoritative production provider.

Before production integration, run the benchmark corpus repeatedly and establish field-by-field authority, failure behaviour, cookie-authenticated behaviour and useful relative cost. In particular, exact `upload_date` remains unresolved, so `getBasicInfo()` cannot currently replace complete detailed acquisition for every scalar query.
