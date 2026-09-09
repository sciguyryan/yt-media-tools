# Downloader future work

## Purpose

Downloader 1.7.0 has useful foundations: file and standard-input targets, output profiles, versioned parameter profiles, explicit CLI precedence, raw yt-dlp format selectors, dry-run command planning, archive-backed queue reconciliation and atomic removal of completed IDs. The next programme should turn those foundations into a clearer and more resilient download-planning system before adding a large number of new switches.

Downloader should remain a focused yt-dlp orchestrator rather than trying to replace yt-dlp. Its value is in providing predictable policy, safe persistent workflows, useful defaults, clear diagnostics and composability with Discover. Expert users should still have deliberate escape hatches where yt-dlp's native expression language is the right tool.

Downloader is the preferred next implementation target because Discover 0.26.6 is already a hardened baseline while Downloader still has more policy embedded directly in command construction and less separation between configuration, planning, execution and recovery.

## Working rules

Every phase must preserve the behaviour it does not deliberately change. Configuration precedence must remain deterministic and documented. Explicit CLI settings take precedence over selected parameter-profile values, and expert overrides must not be silently rewritten by higher-level policy.

Queue safety is a core invariant. An item must not disappear from a file-backed queue merely because yt-dlp started it, partially wrote it or exited unexpectedly. Completion must continue to be tied to a point where successful post-processing is proven. Queue rewrites must remain atomic and preserve unrelated lines.

Documentation and tests are release requirements. `DOWNLOADER-README.md`, the top-level `README.md`, `TODO.md` where appropriate and `CHANGELOG.md` must stay consistent with the implemented command surface. Help and `--examples` should contain practical examples for non-obvious workflows.

## Phase 1 - architecture, cleanup and resolved plans

Refactor without deliberately changing download semantics. Separate the current flow into clear responsibilities for:

- CLI parsing;
- defaults and parameter-profile loading;
- configuration precedence;
- output-profile resolution;
- input-source resolution;
- `DownloadPolicy` or equivalent typed policy;
- `DownloadPlan` or equivalent resolved plan;
- yt-dlp command generation;
- execution;
- queue and post-run actions.

Audit dead code, stale compatibility paths and duplicated validation while doing this, but keep compatibility behaviour that is still intentionally supported.

Add a proper `--explain` surface. Unlike `--dry-run`, which remains useful for showing the exact resolved yt-dlp command, explain output should describe why the plan has its values: selected parameter profile, output profile, format policy or raw selector, authentication source, archive, playlist behaviour, temporary/output paths and other relevant decisions. A machine-readable JSON explain form should be considered if it can be added cleanly.

Build a deterministic plan-level conformance suite so most policy behaviour can be tested without launching yt-dlp.

## Phase 2 - typed operational policy and parameter-profile expansion

Expand the existing versioned parameter-profile system so common operational policy no longer has to be hard-coded or repeated on every invocation.

Candidate settings include:

- download-rate limits;
- concurrent fragment count;
- general retries;
- fragment retries;
- retry/backoff behaviour;
- throttled-rate handling;
- archive path;
- temporary path;
- carefully bounded extractor arguments;
- cookie-file selection;
- browser-cookie selection;
- playlist enablement and traversal controls.

Do not turn the JSON profile into an arbitrary list of yt-dlp CLI arguments. Downloader-owned concepts should remain typed and validated. Unknown keys and wrong types should continue to fail clearly.

Support `--cookies-from-browser` or an equivalent typed setting so browser cookies can be used without exporting a cookie file. Authentication configuration must remain distinct from secrets. Profiles may identify a browser or cookie-file path, but the project should not encourage embedding reusable tokens or credentials in distributable configuration.

The architecture should remain flexible enough to pass current yt-dlp extractor requirements, including evolving YouTube client/PO-token configuration, through explicit controlled mechanisms without inventing a Downloader-specific authentication protocol.

## Phase 3 - declarative format policy

The implemented selection contract includes: hard resolution/FPS bounds, fallback-friendly codec/FPS/HDR/audio-channel preferences, merge-container choice, deterministic compilation and raw-selector authority. Language preference and filesize policy remain deliberately deferred until extractor consistency and exact-versus-approximate size semantics can be specified conservatively. Audio-only and stream-mode policy remains assigned to Phase 7 rather than being duplicated here.

Build a first-class format policy above yt-dlp's native selector language. Candidate dimensions include:

- maximum and minimum resolution;
- preferred video codec;
- preferred audio codec;
- FPS requirements or preferences;
- HDR/dynamic-range preference;
- preferred container;
- audio channel requirements;
- language where relevant;
- known or approximate filesize constraints where reliable enough;
- video-only, audio-only and combined-stream behaviour;
- explicit fallback policy.

Downloader should compile the resolved policy into yt-dlp format selection/sorting arguments. The translation must be exhaustively tested with exact expected commands.

Raw `-f/--format` remains the expert authority. If the user supplies a raw yt-dlp format expression explicitly, Downloader must not silently reinterpret it through the declarative format policy.

Use terminology compatible with Discover's future format-aware query model where that improves consistency, but keep the implementations independent. Discover asks what formats exist; Downloader decides what acceptable format to retrieve.

## Phase 4 - subtitles, thumbnails, chapters, metadata and SponsorBlock

Move post-processing and associated-artefact choices into explicit policy. Cover, where yt-dlp supports them reliably:

- manually supplied subtitles;
- automatic captions;
- subtitle language selection;
- subtitle format;
- embedded subtitles versus sidecar subtitles;
- thumbnail download and embedding;
- metadata embedding;
- info JSON sidecars;
- chapter embedding;
- SponsorBlock marking/removal and category selection.

The phase must define what Downloader considers the primary requested output and what counts as an optional associated artefact. This becomes important for later integrity checking and run manifests.

Defaults should remain practical, but policy choices that materially alter media should not be hidden as unexplained constants.

## Phase 5 - queue durability and failure accounting

The archive-backed text queue now has a durable observation layer. Queue runs snapshot the initial target set and archive state, reconcile already archived IDs, retain unresolved entries, and report requested, already archived, newly completed and unresolved targets after execution. Concise summaries are written to standard error, `--queue-report FILE` writes deterministic JSON, and `--failed-targets FILE` writes a reusable unresolved-target batch file. Generated report files use atomic replacement.

The current classification is deliberately conservative. A target that remains queued is reported as unresolved rather than being guessed to be unavailable, skipped or failed. A future executor capable of receiving reliable per-entry yt-dlp outcomes may refine those categories. That work should evaluate structured yt-dlp hooks or the Python API rather than scraping unstable human-readable output.

`--max-failures` remains deferred because the current subprocess architecture does not expose a trustworthy per-target failure count early enough to stop a multi-target invocation safely. A dedicated `--retry-failed` command is also unnecessary while `--failed-targets FILE` already produces an ordinary batch file that can be passed back through `--input-file` or as a positional file.

Post-processing failure, completion-callback failure and atomic queue-rewrite failure are simulated at the orchestration boundary. An ID remains queued whenever successful completion cannot be established. These failure-boundary tests are required regression coverage rather than manual acceptance checks.

Do not introduce a database merely to make the queue look more sophisticated. The durable text-file queue and optional reports remain the preferred model unless future requirements demonstrate a concrete need for stronger storage.

## Phase 6 - run manifests and output integrity

Add an optional lightweight machine-readable run manifest for reproducibility, diagnosis and automation. This is not intended to be forensic evidence and must not make evidential claims.

A manifest may record:

- Downloader version;
- yt-dlp version;
- resolved parameter/output profile names;
- resolved policy;
- input targets;
- start/end timestamps;
- yt-dlp exit status;
- completed targets;
- archive hits;
- failures/unavailable targets;
- resulting output paths;
- generated sidecars.

Investigate optional hashes of completed outputs for ordinary integrity checking. Hashes should be clearly described as verification aids, not proof of authenticity or provenance.

Audit yt-dlp and ffmpeg failure behaviour to determine whether an apparently present output can ever be mistaken for a completed output. yt-dlp's successful completion state should remain authoritative unless Downloader can establish a stronger invariant without introducing false failures. Sidecar expectations should be checked only when the selected policy actually requires those artefacts.

Downloader 1.13.0 records completed primary output paths through an internal `after_move` callback rather than scraping yt-dlp console output. Optional SHA-256 hashes are calculated only for those observed primary files. The manifest reuses the redacted resolved-plan representation, records queue outcomes when available, and deliberately does not invent associated sidecar paths. The deterministic manifest schema, redaction, output-event handling, hashing, interruption and failure boundaries are covered with automated tests and simulated yt-dlp execution.

Actual sidecar-path tracking remains a possible refinement only if it can be based on authoritative yt-dlp events rather than filename inference.

## Phase 7 - first-class audio workflows

Make audio-only operation a deliberate mode rather than requiring users to construct raw format expressions.

The design must distinguish two different operations:

1. select an already available source stream in the requested codec/container;
2. download another representation and transcode it.

Downloader must never blur these together because they have different quality, time and computational consequences. Profiles should be able to state whether transcoding is allowed and what fallback behaviour is acceptable.

## Phase 8 - playlist and range controls

Expand playlist policy with typed controls for indices, ranges, slicing and traversal. Preserve predictable interactions with archive handling and file-backed queues.

Consider deterministic randomisation only if there is a real use case and its interaction with queue persistence is clear. Avoid duplicating yt-dlp options that provide no meaningful Downloader-level policy benefit.

## Phase 9 - live-media workflows

Treat live acquisition as a distinct behavioural mode. Investigate and document:

- waiting for scheduled streams;
- live-from-start behaviour;
- interruption and restart handling;
- transition from live to post-live/VOD state;
- retries appropriate to long-running live work;
- live chat or related sidecars where requested.

Live-specific timing and failure semantics should not be hidden inside ordinary parameter profiles without explanation.

## Phase 10 - partial media and sections

Add deliberate support for downloading only part of an item, such as time ranges or chapter-based sections, where yt-dlp provides a reliable underlying mechanism.

This is intentionally late because it changes the meaning of a target from "retrieve this media item" to "produce this selected derivative portion". Output naming, archive behaviour, queue completion and run-manifest semantics must account for that distinction.

## Phase 11 - hardening and final reconciliation

Stop feature work and perform a dedicated hardening programme:

1. clean up dead/stale code and compatibility paths;
2. audit configuration precedence and every policy-to-command translation;
3. reconcile help, examples and documentation;
4. audit queue and archive invariants;
5. expand deterministic policy/command conformance;
6. add hostile configuration and Unicode/path cases;
7. run property-based testing where it explores meaningful policy combinations;
8. run mutation testing around precedence, queue removal and success/failure boundaries;
9. use coverage diagnostics to identify untested branches;
10. add performance benchmarks only where Downloader itself performs material work;
11. complete a final documentation and release reconciliation.

Routine CI should remain fast. Expensive mutation or stress work should be explicit hardening/release validation rather than an everyday requirement.

## Testing and tooling investigations

The tooling investigations recorded for Discover also apply to Downloader where they solve a real problem.

Hypothesis is particularly promising for configuration/profile precedence, generated valid policies, policy-to-command invariants and queue-state transitions. Mutation testing is particularly valuable around boolean flags, precedence order, completion callbacks and conditions that remove queue entries. Branch coverage can expose untested failure paths. Fuzzing may be useful for profile/configuration parsing but is less central than it is for the yt-sql parser.

Tests should increasingly distinguish pure planning from external execution. Most configuration and command generation should be deterministic and testable without yt-dlp. External-process tests should use controlled fakes/mocks for failure modes rather than depending on live network behaviour. Any useful deterministic behaviour that can be represented faithfully in the suite should be automated; manual verification must not substitute for such coverage.

## Relationship with Discover

The tools should remain independently usable and independently versioned. They may share terminology and small reusable implementation where that is genuinely common, but neither should become a mandatory front-end for the other.

A useful long-term flow is:

```text
Discover determines which media items satisfy a query and can describe known format capabilities.

Downloader applies a user's download policy to those targets and retrieves acceptable representations safely.
```

Standard input/output remains the simplest and most important integration boundary. Future machine-readable reports or manifests may provide richer optional integration without replacing ordinary pipelines.

## Scope boundaries

Downloader should not become a forensic acquisition system, a media library manager or a replacement implementation of yt-dlp. Run manifests and hashes are operational aids. Persistent queues are workflow state. yt-dlp remains the underlying downloader and extractor authority.

The project should continue to prefer explicit typed policy over an ever-growing collection of aliases, while preserving expert access to yt-dlp features where a stable Downloader abstraction would add no value.
