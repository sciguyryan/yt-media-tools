# yt-discover cache v4 design

The cache-size problem started this discussion. A real Discover database can grow to several gigabytes, and v3 gives us a fairly obvious suspect: `metadata_records` stores the complete yt-dlp JSON response for each `(source_url, video_id)`. If the same video turns up through several sources, we can store the whole thing several times. Formats, signed URLs, storyboards, headers and other backend baggage then sit there because `raw_json` is the authoritative record, whether yt-sql ever asks for them again or not.

That looked at first like a pruning job. It isn't. Once `raw_json` stops being the centre of the cache, we have to answer who owns a metadata value, what the identity of the media actually is, how two providers supplying `duration` interact, what "not acquired" means without a JSON blob to inspect, and what happens to source coverage when metadata is thrown away. There is also a multi-gigabyte v3 database to get across the boundary safely. That last part is where this gets uncomfortable: an elegant v4 is not much use if upgrading to it can destroy or silently reinterpret the cache people already have.

This is the record of where we landed. It is not the v4 schema definition yet. A few table shapes and CLI details are intentionally still open because the current tree needs a more mechanical audit before choosing them.

## The v3 shape we are leaving

The detailed record today is:

```text
metadata_records(source_url, video_id, fetched_at, raw_json)
```

`raw_json` is described by the v3 cache code as authoritative yt-dlp JSON. Freshness is layered over the one `fetched_at`: different fields have different maximum ages, and the former `raw.*` language additionally checked that a requested nested path was present. That was better than treating the whole blob as equally fresh, but it still meant one acquisition time stood in for a potentially large set of observations.

Source knowledge is already separate. `source_observations`, `source_entries`, `source_coverage` and `source_frontiers` carry membership, ordering and completeness/frontier information. The existing code is careful not to turn a mere observation into a trusted frontier. Keep that distinction. We spent too much effort getting incremental source behaviour right to blur it during a storage refactor.

The current SQLite connection uses foreign keys, WAL and `synchronous=NORMAL`. Those are facts about v3, not recommendations for the migration writer. We need measurements before choosing bulk-migration pragmas or a compaction strategy.

There are two wrinkles that would be easy to miss if we only looked at the database tables. Specialised YouTube.js and ytmusicapi acquisitions can currently supply a small exact-scalar set, but those specialised results are deliberately not persisted. v4 gives us a chance to fix that rather than treating extension providers as second-class cache citizens.

The other wrinkle was `raw.*`. At the start of the v4 work it was real yt-sql surface, not a debug trick, so removing `raw_json` created a language compatibility question that the database migration was not allowed to decide accidentally. That question was kept explicit until the complete v4 path and a pre-release usage review showed no actual use sufficient to justify the open-ended feature. Issue #142 subsequently removed `raw.*` and its compatibility storage before release.

## Store what Discover can use

The working rule is: persist metadata that is materially usable through a query, plus the state Discover needs to acquire, interpret, resolve and maintain it.

That leaves room for extension providers and future fields without keeping a backend response just because it arrived. If a provider exposes something worth querying, it registers the field. If Discover needs some provider-specific operational state to make acquisition or provenance correct, that can be stored too, but it is not query metadata merely because it came from the same response.

This is a Discover cache, not a general provider object store. That boundary is useful.

## Media identity should not depend on where we saw it

The natural key is `(service, external_id)`: for example `(youtube, <video id>)` or `(twitch, <media id>)`. `service` is the content service, not yt-dlp/YouTube.js/ytmusicapi. SQLite can use a compact integer `entity_id` behind that natural key.

So there will be one `media_entities` identity with `UNIQUE(service, external_id)`, and provider metadata/source observations point at it. No UUID for now. We do not have a cross-database identity problem that needs one.

This is a fairly important departure from v3. Seeing one YouTube video through three logical sources no longer justifies three copies of its detailed metadata.

## Provider-owned observations

A provider should say what it can supply. SQLite columns should not accidentally become the definition of the query language.

The code-side definition needs a stable provider key, a provider schema revision, field definitions and their yt-sql types, storage mappings, acquisition groups, applicability/capability information and default freshness. The database keeps the persistent half: stable provider identity, registration order, policy overrides, the provider schema revision responsible for data on disk, and enough of the field contract to understand that data later.

Provider metadata can live in provider-owned tables keyed by `entity_id`. I expect that to be one main table per provider in the ordinary case, but I don't want to legislate that before we inventory the structured fields. If yt-sql treats some data relationally, a child table may be the honest representation.

Several providers can implement the same logical field. yt-dlp and YouTube.js both supplying `duration` does not create two query fields called duration. They are two observations of the same thing.

Which one wins is policy. We settled on a provider default priority with per-field overrides. Equal priorities are legal and break on a persistent `registration_order`, not whichever row SQLite happens to return first. Resolution stays dynamic so changing a priority does not rewrite millions of cached values. yt-dlp will probably start with the highest general default because that is closest to today's behaviour, but there is no useful reason to declare it universally authoritative.

If a provider is removed or disabled, its cache does not evaporate. A fresh scalar value whose persisted field contract is sufficient for core to interpret it can still be useful. Obviously it cannot be refreshed until the provider is back. More complicated provider-specific values may need the provider present to interpret them; the field audit will tell us whether we actually have any.

### Extensions and field names

Extensions should be able to register genuine fields without editing core every time. Claiming an existing shared name is a semantic claim, though: an extension that registers `duration` is saying it means the same `duration`, with the same logical type and comparison behaviour.

Something provider-specific needs a stable namespace. We have not chosen the yt-sql spelling for that yet, and the cache design should not choose it by accident. It has to compose with qualification and postfix syntax.

There is no miscellaneous provider JSON type in this model. Persisted types are types yt-sql understands and can serialise, compare and migrate deterministically. Structured/list values need an explicit mapping rather than an escape hatch.

The current field/type inventory is now represented by the stable yt-sql schema and provider registry. Registered scalar fields carry explicit logical types; stable collections retain their established collection contracts while their first-class v4 persistence remains separate work.

### Provider schemas will move independently

Adding a ytmusicapi field should not force the whole cache from v4 to v5. Provider-owned persistent schemas therefore need their own revisions.

A new field starts as not acquired for old entities unless a provider migration can actually establish it. Removing a field makes it semantically invisible; we do not have to rebuild a huge table immediately just to erase a dead column. A type/meaning change is different and needs an explicit provider migration. Quiet coercion here would be a nasty source of old-cache bugs.

Core can provide migration plumbing. The provider owns the meaning of its historical representation.

## The states behind one field

The resolver is simple to describe: walk candidate providers by effective priority and registration order and take the first fresh, usable value. SQL NULL does not stop the walk. `0`, `false`, `''` and a valid empty collection do.

The implemented scalar resolver follows that rule through the persistent registry rather than maintaining a second precedence policy. It retains the highest-precedence fresh known NULL while continuing to look for a lower-priority fresh value. If no fresh value exists, that known NULL becomes the resolved result. Stale observations are retained as unresolved fallback state for acquisition and diagnostics, but are not promoted over current information. The result keeps the winning provider key and full observation so provenance, age and failed-refresh context remain inspectable.

Underneath that are distinctions we already rely on: value, known NULL, not acquired, unsupported, inapplicable, failed acquisition and stale observation. This is one of those lists that really does need to be complete. Collapsing "not acquired" into NULL would change query/acquisition semantics.

It does not follow that we need seven status columns per field. In the common case the state can be derived. No acquisition record means not acquired. A successful acquisition group plus a NULL column can establish known NULL. Unsupported/inapplicable often comes from capabilities. Failures belong to acquisition state, not to the value column.

One timestamp per provider/entity is still too coarse. Providers need named acquisition groups matching their real fetch boundaries, with state keyed conceptually by `(entity_id, provider_id, acquisition_group_id)`. Fields in a group can have different freshness lifetimes even though they were acquired together.

There is a trap here. A successful group may imply value-or-NULL only for fields the acquisition genuinely resolved. If a backend can resolve fields independently, putting them in one group would manufacture known NULLs. Registration has to tell the truth about that boundary.

The implemented scalar observation layer keeps this derived rather than adding a status row per field. Unsupported comes from the provider declaration, definite applicability mismatches from the provider contract and known source context, and no group state means not acquired. A group that has never succeeded but whose latest attempt failed is failed acquisition, not NULL. After a success, the stored column is either a value or known NULL and its age comes from that group's `last_success_at` under the field's effective freshness policy. If a later refresh fails, that failure remains visible alongside the earlier observation; it does not rewrite the observation timestamp or manufacture staleness. A successful group with no provider metadata row is inconsistent persisted state and is rejected rather than interpreted as NULL.

The existing acquisition paths treat provider failures as recoverable: specialised providers can fall through to another path, and per-video failures can be skipped without proving that metadata is absent. The v4 group state therefore keeps `last_attempt_at` separate from `last_success_at`. A failed refresh records its failure category and latest attempt time but preserves any earlier successful acquisition. A later success clears the failure marker. This gives later field resolution enough history to distinguish "the last refresh failed" from "this group has never succeeded" without turning either case into SQL NULL.

## Freshness is attached to an observation

A stale high-priority value should not force reacquisition merely because its provider is preferred. If a lower-priority provider already has a fresh usable observation, use it. When the preferred provider is refreshed later it naturally wins again.

Known NULL ages too. Unsupported/inapplicable capability information is different and may change with a provider/schema capability revision rather than a TTL.

Provider fields carry sensible default freshness policies; users can override them globally, per provider and, where there is a reason, per field. `immutable` is useful for data that does not expire with time but can still be explicitly invalidated. `always-refresh` exists for the opposite case. I expect it to be rare.

The exact defaults need to be reconciled with the v3 values rather than invented afresh. v3 already has useful evidence about which fields were considered volatile.

## Source state is not metadata

This was an important point in the discussion because the tempting pruning implementation gets it wrong.

Suppose Discover enumerated a channel yesterday and knows that video X belongs to it. Today metadata retention deletes the yt-dlp record for X. We still know X was in the enumeration. A later query can reacquire X's metadata without enumerating the whole channel again. Deleting the source observation just because detailed metadata expired would throw away useful and rather different knowledge.

So v4 keeps the layers separate:

1. media identity;
2. source/facet membership and ordering;
3. provider metadata observations;
4. coverage/frontier knowledge;
5. acquisition state.

That is a conceptual list, not a demand for exactly five tables.

Source/facet state needs a `last_enumerated_at`-style timestamp for retention. I don't think per-observation `last_observed_at` buys us enough to justify millions of extra writes just for pruning. When source state is pruned, do it coherently at the source/facet level: observations/order plus the coverage/frontier claims that depend on them. We cannot leave "complete through N" behind after deleting the evidence that made it true.

Metadata pruning is independent. It removes a provider's contribution for an entity when that contribution is old enough under the retention policy. The useful retention unit here is the provider/entity record, not individual fields. Freshness can stay granular while deletion stays coherent. A provider record's most recent successful acquisition can be derived from its acquisition groups.

After either sort of pruning, `media_entities` becomes garbage only when nothing persistent still refers to it. Source state may legitimately keep an identity alive after all detailed metadata is gone.

The #129 source-state audit keeps those boundaries literal in the v4 persistence model. A stable source/facet identity owns enumeration telemetry and ordered membership, while membership points to `media_entities` rather than to a provider record. Coverage and frontier remain separate stronger claims rather than being inferred from observation or membership. The ordered membership table deliberately has no per-entry pruning timestamp: source/facet retention can use the source-level observation time and remove the coherent source-state unit instead of rewriting millions of membership rows merely to age them.

## Invalidation, pruning and making the file smaller

These turned out to be three operations, and keeping them separate avoids several odd policies.

Invalidation says "don't trust this as current". Pruning removes cached state. Compaction asks SQLite to return unused pages to the filesystem. Deleting rows does not necessarily shrink the file, which is fine: SQLite can reuse those pages.

There is no automatic age-based deletion by default. Users who opt into retention can have opportunistic/throttled maintenance, but it should call the same pruning machinery as an explicit maintenance command. Compaction remains explicit; running a heavyweight `VACUUM` because a query happened to trigger retention would be surprising and potentially very expensive. The implemented maintenance path preserves that separation. `--cache-compact` is an explicit operation. With the current cache configuration (`journal_mode=WAL`, `synchronous=NORMAL`, and no configured `auto_vacuum`), it first attempts `PRAGMA wal_checkpoint(TRUNCATE)` and refuses to continue when an active reader or writer prevents that checkpoint. It then runs `VACUUM` only when the freelist reports reusable pages. Databases using a non-WAL journal do not receive a WAL checkpoint, and `auto_vacuum=FULL` databases do not receive a redundant explicit vacuum. Incremental auto-vacuum is not enabled automatically: adopting it would change database configuration and therefore requires separate evidence and policy rather than being smuggled into maintenance.

We rejected `last_queried_at` as a retention signal. "Queried" gets murky once planners, failed predicates and partial acquisitions are involved, and turning reads into writes for this purpose is unattractive. Retention is based on successful acquisition/refresh and source enumeration instead.

Explicit pruning should be previewable. The preview and execution ought to come from the same internal plan so the dry run is not a second approximation of the deletion logic. Useful output includes provider-record counts, source/facet state affected, identities that would become orphaned and the distinction between logical data removed and disk space that compaction might later reclaim.

For a large destructive operation an interactive `[y/N]` is sensible. Non-interactive use cannot sit waiting for a terminal that is not there; explicit authorisation will be needed when a configured threshold is crossed. Automatic retention is already authorised by configuration and therefore cannot prompt.

Command names and destructive-operation thresholds remain a maintenance-surface decision. They should be derived from the existing cache CLI/config conventions when that surface is implemented rather than being invented in this schema document.

### Maintenance planning contract

Retention policy is opt-in. The default policy has no provider or source-state age limit and therefore selects nothing for deletion.

The maintenance planner is read-only and returns an immutable selection plan. Provider metadata is selected as a coherent provider/entity contribution using the most recent successful acquisition for that provider/entity, not individual field freshness and not the most recent failed attempt. Source state is selected as a coherent source/facet unit using its source observation time. A timestamp exactly on the retention boundary is retained; selection requires it to be strictly older than the configured window.

Preview and execution consume the same immutable plan object. The executor does not recalculate retention eligibility, so state that becomes eligible after a preview is not silently added to that execution. Provider pruning removes the selected provider metadata contribution and its acquisition history together. Source pruning removes the selected source/facet boundary, relying on foreign-key cascades to remove its observation, ordered membership, coverage and frontier claims. Entity garbage collection runs only after all selected contributions and source state have been released.

Execution is transactional across the complete plan. A failure rolls back provider pruning, source pruning and entity collection together. Configured automatic retention calls the same planner and executor as explicit maintenance and is treated as pre-authorised by that configuration. It does not imply compaction.

The maintenance core does not choose a destructive-operation threshold. The current Discover cache interface has no established retention or destructive-maintenance threshold to inherit. Instead, explicit callers supply the configured threshold to the authorisation helper. Plans below that threshold may proceed as an explicit maintenance request; plans at or above it require affirmative interactive confirmation or explicit non-interactive pre-authorisation. This keeps the eventual CLI/config spelling and threshold policy outside the persistence model while enforcing safe behaviour once a threshold is configured.

Compaction and cache status remain separate later maintenance layers.

## Cache status should explain what is on disk

The maintenance status surface is read-only and has a structured representation independent of terminal formatting. It reports the legacy cache schema version and v4 registry revision, persistent provider registrations and revisions, provider metadata/acquisition counts, media-entity counts, coherent source-state counts, configured retention and retention-eligible counts, plus SQLite page, free-page, database-file and WAL observations. Persisted providers that are no longer installed/declared and provider revision mismatches are visible without reconciling the registry as a side effect of inspection.

`--cache-status` presents this snapshot without requiring a source or contacting YouTube. `--cache-status-format json` exposes the same status model for machine consumers. The SQLite figures are observations only: free pages or WAL size do not imply that status should checkpoint, vacuum or otherwise compact the database. Those decisions remain part of the explicit compaction phase.

Once provider schemas and maintenance exist, a useful status command becomes more important than it is today. At a minimum we will want cache schema/version, provider registrations/revisions, entity/provider-record counts, acquisition/source-state summaries, configured retention, stale/unavailable-provider information and SQLite file/free-page/WAL information. Verbose output can go deeper.

Long operations such as migration, pruning verification and compaction should share progress/event plumbing. Normal mode needs enough progress to prove a multi-hour operation is alive. Verbose can add provider/table counters and timings. Debug remains implementation detail under the existing debug contract. Per-record chatter would make the useful messages disappear.

## `raw.*` was deliberately removed

The original v4 design refused to keep a complete arbitrary backend blob merely so `raw.foo.bar` could continue reaching into it. Early implementation therefore separated registered metadata from a reduced compatibility remainder while the language requirement was still unresolved.

The completed pre-release usage review found no actual use of `raw.*` sufficient to justify its language, acquisition, persistence, migration, maintenance and verification cost. Issue #142 removes the namespace and the compatibility store rather than carrying an unused escape hatch into release. Useful data must have an explicit registered field or supported collection contract.

The historical v3 `raw_json` column remains migration input only. Migration reconstructs supported registered scalars and the closed `tags`, `categories`, `formats`, `chapters` and `thumbnails` collection families, then discards arbitrary unregistered remainder. Fresh-v4 and migrated-v4 databases therefore converge on the same schema without a generic raw payload. The dedicated raw metadata audit retains the reasoning and temporary compatibility history that led to this decision.

## Cache names and finding an old database

From v4 onwards, put the schema version in the cache filename. The exact basename can follow the current path conventions once we inspect them, but conceptually this is `...-v4.sqlite`, then `...-v5.sqlite` later.

The old unversioned filename is the legacy v3 candidate. A selector can look for the current version, then recognised older versioned caches in descending order, then the unversioned v3 name. Filename only identifies a candidate; the schema/version inside the database still has to agree.

If the newest candidate is corrupt, incomplete or mismatched, stop and report it. Silently falling back to an older cache would hide a failure and potentially resurrect stale state. A fresh current cache is created only when there is no recognised historical cache waiting to be dealt with.

Migration working files are not candidates. Retained old databases also need naming/state that keeps them from being mistaken for the active cache.

## Migrating v3 is the risky part

The migration contract is deliberately stronger than "works on my cache". If Discover advertises a migration from a schema, every structurally valid database conforming to that source schema is supposed to migrate without losing information that has a defined target representation. Years later, that should still be true.

Physical SQLite corruption is outside that promise. Weird-but-valid rows are not. We need a machine-testable definition of structurally valid v3 so we cannot move the goalposts when an awkward old database appears.

The migration should preserve what v3 actually knows: identity, queryable metadata with a v4 representation, recoverable provenance, timestamps at the precision v3 had, source/facet observations, coverage/frontiers and other valid state. It should not invent precision. If v3 has one timestamp where v4 has several acquisition groups, carry the timestamp where it is justified; don't fabricate a history we never recorded.

### Pass the parcel

Future upgrades should chain `v3 -> v4 -> v5 -> v6`, not teach v6 how every historical schema worked. Each transition is a black box that understands its source, its target and the historical repairs it owns. If we discover a valid old v3 oddity in 2028, the repair belongs in `v3 -> v4`.

The coordinator only needs to select the next hop. Shared code can provide SQLite checks, progress/events, logging, batching and disk-space helpers, but I would resist building an elaborate migration framework whose abstractions are more complicated than the first two migrations using it.

That coordinator boundary now exists. A registered transition says which schema version it consumes, which version it produces and how to execute that hop. The coordinator can plan and run a chain such as `v3 -> v4 -> v5`, but it cannot inspect or reproduce the transformation inside either transition. A completed hop supplies the source database for the next one. An incomplete destination stops the chain there.

The result contract is intentionally small as well. A transition reports its source and target versions, destination path, explicit complete/incomplete destination state and an optional message. The coordinator checks that the returned versions and path agree with the hop it actually asked for. That catches a surprisingly dangerous class of wiring mistakes without making the coordinator understand migration internals.

A transition roughly does this: validate the source; detect/apply its known pre-transition fixes to controlled migration state; run its phases; validate the target; return a successful database only at the end. Fixes should be independently testable, including already-fixed and unfixable cases. The shared workflow now represents those steps directly, but the transition still owns their meaning. The real v3-to-v4 integration also exposed one necessary final boundary: target validation runs before destination finalisation, so a database is not marked complete merely because its transformation phases finished.

### Keep v3 untouched

For v3 to v4, build a new database beside the old one. Do not rewrite the only copy of a several-gigabyte cache while changing its storage model.

The destination starts explicitly incomplete and becomes complete only after migration and verification. The ordinary cache opener refuses an incomplete database even if somebody has renamed it by hand.

If the run fails, v3 is still usable. The half-built v4 is normally removed after diagnostics; keeping it for investigation is an explicit choice because it may itself be huge.

We discussed resumability and decided against it. Batches are useful for transaction/WAL/memory bounds, but they are not checkpoints. A resumed migration would have to prove that the source, provider registrations, configuration and migration code still match the assumptions behind an old checkpoint. That is a lot of machinery and a dangerous thing to get almost right. Restart from the protected source instead.

This does mean an interruption can waste hours. Say so before starting. Better still, front-load every failure we can predict.

Ctrl+C should stop at a safe boundary where practical, close SQLite cleanly, finalise the migration log as interrupted/failed and handle the destination according to policy. A power cut may leave `_in-progress`; that is one reason the destination's incomplete marker matters.

### Know whether it will fit before starting

Side-by-side migration needs disk space. A generic "old size times 1.2" guess is not good enough when `raw_json` is precisely the thing making v3 large.

Once the v4 schema exists, estimate from the actual v3 composition: entity/provider/source rows that will survive, target indexes/bookkeeping, migration journal/WAL needs, verification work and a safety reserve. Record the estimate and actual result so the estimator can improve with real migrations.

If the destination filesystem plainly cannot fit the job, stop before doing expensive work. An alternate cache/migration path is a useful escape. There is no in-place fallback. We might eventually allow an expert to relax a conservative safety margin, but not to override arithmetic that says the destination cannot fit.

### Batches, indexes and SQLite settings

These are measurement questions. Use bounded destination batches. Build non-essential indexes after bulk insertion if that is actually faster. Keep constraints early when they are useful for catching bad migration output. Choose migration-specific pragmas from benchmarks on realistic databases, not because a blog post says bulk imports like them.

The source being protected does let us trade some destination durability for speed if the evidence supports it. Still, a corrupt destination discovered after four hours is expensive even when it is disposable.

### Verification is not one checksum

Cheap invariants can run over the whole result: SQLite integrity, foreign keys, schema/revisions, uniqueness, dangling references, migration accounting and source/coverage relationships.

Semantic equivalence is more expensive, so standard runtime verification can sample it. The sample should scale with the database, be deterministic/reproducible and deliberately include rare strata: providers, known NULLs, source/facet state, odd metadata states and records touched by pre-transition fixes. If a fix only touched 23 rows, checking all 23 is more useful than hoping random sampling finds one.

One semantic mismatch fails the migration. There is no acceptable mismatch percentage.

For users, named levels such as `standard`, `thorough` and `exhaustive` are clearer than a mysterious percentage. `standard` is Discover's minimum certification and still includes all mandatory structural/accounting checks. Stronger modes can spend more time on semantic comparison. We will choose the actual sampling bounds after measuring the cost.

### The tests outlive v4

If we promise v3 migration, its tests stay.

Keep an immutable/reference v3 fixture that exercises the real schema: NULL and not-acquired cases, timestamps, Unicode and awkward values, multiple source/facets, coverage/frontiers, provider/provenance state and `raw_json` containing both material that should survive and baggage that should not. The expected v4 result/query outputs should be independently authored rather than generated by the transformer under test.

We also need invalid fixtures or deterministic mutations that break individual v3 invariants and fail for the right reason. Inject a late migration failure after some destination batches have committed; that is the case most likely to expose an incomplete database accidentally being treated as usable.

When v5 arrives, do not regenerate the v3 fixture using v5-era code. Keep the historical thing. Test `v3 -> v4`, and test the supported full chain as well.

### Leave a useful log behind

A migration that runs for hours needs a permanent diagnostic trail. Start with a name along these lines:

```text
migration_20260928T132645_v3-to-v4_in-progress.txt
```

then atomically finish it as `_success.txt` or `_failed.txt`. A hard crash leaving `_in-progress.txt` is itself useful evidence.

The header should capture non-sensitive context: Discover/source/target versions, source size, relevant SQLite version/configuration, loaded provider/schema revisions, policy choices, available space and the preflight estimate. During the run, record phase changes, bounded counters, fixes, timings and significant warnings. Finish with accounting, verification, sizes and cut-over/source-cleanup outcome.

Do not log raw payloads, cookies, credentials, signed URLs or HTTP headers. The log should still be enough to investigate a four-hour failure after the failed transition database has been cleaned up.

Terminal progress and the permanent log can consume the same internal event stream at different verbosity. We don't need two logging systems.

### Cut-over, then carry on with what the user asked for

Migration happens before partial query/acquisition work. Discover remembers the operation that triggered startup, migrates and verifies, switches to v4, applies the chosen old-cache cleanup policy and then continues the original operation. Failure means the original operation never starts.

For an interactive run, show the migration policy before the expensive part. The defaults we discussed are to remove the old database after a fully verified successful cut-over and not to retain a failed transition database. The permanent migration log stays either way.

Startup authorisation is now explicit. Interactive startup requires an affirmative confirmation before a supported mandatory migration begins. Non-interactive startup never reads from standard input and automatically authorises the supported mandatory migration under the documented default policy. Corrupt, incomplete, mismatched or otherwise blocked candidates are not authorisation questions and remain fatal startup conditions.

## Current implementation boundary

The complete v4 path now includes the frozen v3 validity contract and historical fixture/oracle, provider registry, deduplicated entity metadata, acquisition state, source/facet persistence, registered scalar storage, closed storage for the five supported yt-dlp collection families, durable v3-to-v4 migration, managed startup discovery/cut-over and migration presentation. The former `raw.*` language and compatibility representation were removed before release after usage review found no actual use sufficient to justify their continuing cost.

The remaining cache-v4 work is measurement and reconciliation. Issue #135 benchmarks the representation and migration path we actually intend to keep, then uses those measurements to revisit provisional sizing, batching, verification, SQLite, pruning and compaction choices. The accepted v3 contract remains permanent migration evidence rather than an active runtime design target.

### Transitional source-state integration

The v3 source-state tables remain part of the live Discover cache while the wider cache-v4 acquisition cut-over is incomplete. Opening the cache imports existing source observations, ordered entries, coverage claims and trusted frontiers into the v4 entity-backed representation. The import is idempotent and does not promote an observation into coverage or frontier trust.

During this compatibility period, source-state mutations are mirrored into v4. Provider metadata may therefore be pruned and reacquired without erasing enumeration knowledge or requiring the source to be enumerated again. The legacy source-state tables can be retired only as part of the wider runtime cut-over once no supported path depends on them.

### Migration execution plumbing

The migration coordinator remains deliberately ignorant of transition internals. Shared execution plumbing now covers the pieces that do not need schema knowledge: SQLite integrity checks, destination disk-space observations, bounded lazy batches, structured progress events and append-only migration logs.

Progress and permanent logging use the same event object. A transition can emit an event once and attach terminal or other consumers alongside the permanent log sink, rather than maintaining a second account of migration progress. Each logged run is finalised as complete, incomplete, failed or interrupted. Exceptions and `KeyboardInterrupt` still propagate after the final record has been written.

The disk-space helper reports available space against a requirement supplied by the transition. It does not decide how much space a migration ought to require. Likewise, the integrity helper exposes SQLite's result without deciding which transition phase should run it. Validation, historical repairs and migration phases remain transition-owned rather than becoming coordinator policy.

### Transition-owned migration workflow

A schema transition now has a small ordered workflow around its actual transformation: source validation, transition-owned historical repairs, named migration phases and target validation. The coordinator still knows none of those details. It selects the hop; the transition decides what makes its source valid, which old defects need repairing, how its data moves and what proves the destination is usable.

Historical repairs make their state explicit. A repair reports either that it applies or that it has already been applied. Applicable repairs run before migration phases; already-applied repairs are recorded through the ordinary event stream and skipped. A failed applicability check or repair stops the transition rather than allowing later phases to guess what state the source is in.

Completion is deliberately late. The workflow does not create a complete transition result until target validation has succeeded. Source-validation failure, repair failure, phase failure, target-validation failure and interruption therefore cannot leave a result that the coordinator could mistake for a usable next-hop source. The shared migration log still finalises those runs as failed or interrupted, while the underlying exception or interruption remains visible to the caller.

### The real v3-to-v4 transition

The common workflow is now exercised by a real side-by-side v3-to-v4 transition rather than only synthetic test hops. The transition opens the v3 source read-only, checks SQLite integrity and the frozen v3 structural boundary, then uses SQLite backup to create a separate destination. All transformation work happens against that destination.

Current v3 databases can already contain transitional `cache_v4_*` tables because #128-#130 mirror new writes and source state while the runtime still uses schema v3. Those tables are useful compatibility scaffolding, but they are not authoritative migration input. The durable transition therefore discards copied transitional v4 tables and rebuilds the target from the v3 facts. That avoids allowing the age or completeness of bridge material to change the result of a later migration.

Detailed records are replayed in acquisition-time order into the registered yt-dlp provider representation. This matters when the same media identity exists under several v3 source URLs: v3 stores those records separately, while v4 provider metadata is entity-scoped. Processing older acquisitions before newer ones preserves the newest provider observation without violating acquisition chronology. Supported collection families are persisted through their closed entity-scoped representation; arbitrary unregistered backend material is discarded. Equal timestamps use source URL and video ID as deterministic tie-breakers.

The source-state bridge then imports observations, membership, coverage and frontiers into v4 entity identity without strengthening their meaning. Once the v4 representation has been built, the destination drops the copied legacy runtime tables. Structural validation checks SQLite integrity, required v4 tables and the explicit incomplete marker. Only after that validation succeeds does destination finalisation write schema version 4 and change the migration marker to `complete`.

The transition itself remains separate from startup selection and cut-over policy. Managed startup now invokes this durable transition when discovery resolves a supported historical v3 cache, verifies the resulting v4 candidate, re-resolves it as active and only then applies the configured old-cache cleanup policy.

### Historical v3-to-v4 fact and sizing contract

The durable migration treats v3 as a historical fact source rather than as a representation to copy mechanically. A v3 `metadata_records` row contributes its row `video_id` to v4 media identity, its queryable registered scalar metadata to the yt-dlp provider representation, its supported collection values to the closed yt-dlp collection representation, and its `fetched_at` value as the acquisition time at exactly the precision v3 recorded. Arbitrary unregistered backend material and internal `_yt_sql_` material are discarded rather than retained merely because they occupied space in `raw_json`. The migration must not infer per-field acquisition times or other finer history that v3 never stored.

Source state maps independently of detailed metadata. `source_observations` becomes v4 source observation state; `source_entries` preserves source ordering against v4 media identities; `source_coverage` preserves the recorded coverage observation, counts, completeness and reason; and `source_frontiers` preserves the verified frontier, known-entry count, head identity and overlap confirmations. Registry/provider declarations and v4 indexes are target-schema structure rather than historical v3 facts.

Preflight sizing therefore measures v3 composition rather than multiplying the old database size by a constant. The analysis records detailed-record and distinct-media counts, each source-state cardinality, total historical raw JSON bytes, registered scalar material and supported collection material. The estimate combines the surviving registered representation with the materialised current v4 schema size, conservative row allowances and a page/index reserve derived from rows the v4 schema will actually index. The estimate is deliberately explainable and conservative; #135 must replace provisional allowances where measurements justify better defaults.

### Historical migration execution contract

The v3-to-v4 transition is restartable rather than resumable. Preflight validates the protected v3 source and checks the composition-aware v4 space estimate before a destination is created. The original v3 database is opened read-only and remains authoritative throughout the transition. A newly copied destination is marked `migration_state=incomplete` before any v4 population work is allowed to commit, and an existing destination is never reused as a checkpoint.

Detailed metadata population commits in bounded batches. A failure within a batch rolls that batch back, while earlier committed batches may remain in the disposable incomplete destination. This is intentional: committed work makes migration progress durable enough for predictable failure behaviour, but the incomplete marker prevents that partial database from becoming a usable cache. Restart requires disposal of the incomplete destination and a fresh migration from the unchanged v3 source.

Indexes whose maintenance would add unnecessary work during bulk population may be deferred and rebuilt after population. Target validation still requires the finished structural state, including rebuilt indexes where applicable. Schema version 4 and `migration_state=complete` remain finalisation facts written only after all migration phases and target validation succeed. A late failure can therefore leave substantial v4 data on disk, but it cannot produce a destination that advertises itself as complete or as schema v4.

### Historical migration certification

A v3-to-v4 destination is not eligible for finalisation merely because its tables were populated successfully. Target validation first applies exhaustive inexpensive invariants to the whole database, including detailed-record accounting, the complete set of media identities represented by v3, registered collection storage, and the cardinalities of source observations, entries, coverage and frontiers. These checks are intended to catch loss, duplication and structural disagreement before more expensive semantic comparison.

Semantic certification compares the protected v3 facts with their actual v4 representations. Registered scalar metadata, supported collections and detailed acquisition provenance are compared against the appropriate historical v3 facts, preserving the exact `fetched_at` value as the v4 acquisition timestamp rather than manufacturing finer history. Source identity, source kind, observations, ordering, coverage and frontiers are compared exhaustively, including frontier head identity and all recorded timestamps and counts. Arbitrary unregistered backend material has no target representation to certify. Registered yt-dlp datetime fields retain their numeric Unix epoch representation in INTEGER-affinity columns; the logical `datetime` type governs query semantics and must not silently coerce those provider values to text.

Normal verification uses deterministic stratified sampling for the potentially expensive detailed metadata comparisons while retaining exhaustive structural/accounting and source-state checks. The sample combines lexical positions with stable SHA-256 identity ordering so the same database produces the same verification set independently of process ordering. Full verification compares every latest media record and every supported collection representation. Any semantic mismatch is fatal and occurs while the destination is still marked incomplete, so schema-v4 finalisation cannot follow a failed certification.

### Permanent historical migration evidence

The accepted v3 fixture, its source-fact oracle and the independently authored v4 semantic expectation are permanent migration evidence rather than temporary implementation scaffolding. Regression coverage verifies the expected v4 identity, latest registered metadata, supported collections, acquisition times, source ordering, coverage and frontiers without depending on SQLite surrogate identifiers. The fixture deliberately retains arbitrary historical backend material so regression coverage can prove that unsupported remainder is discarded rather than smuggled into v4. Separate cases preserve rejection of invalid historical states, restart-only handling after interruption and late failure, and the rule that permanent migration logs contain progress and outcome information rather than raw historical payloads or representative secret-bearing material.

### Versioned startup discovery and active-cache resolution

From schema v4 onwards the ordinary cache filename identifies its schema generation. The current v4 candidate is `metadata-v4.sqlite3`; the historical unversioned `metadata.sqlite3` filename identifies the legacy v3 candidate. The filename establishes only which schema the candidate claims to contain. Startup must inspect the database read-only and require its internal schema and migration state to agree before the candidate can be trusted.

Discovery and active-cache selection are separate concepts. Discovery reports recognised files in current-to-historical precedence order. Resolution may identify a complete current candidate as active, identify a valid historical candidate as requiring migration, report that no recognised cache exists and a fresh current cache is required, or block startup because the newest recognised candidate is corrupt, incomplete or mismatched. A historical candidate is never itself returned as the active current cache.

The newest recognised candidate controls resolution. If `metadata-v4.sqlite3` exists but is corrupt, incomplete, structurally invalid or internally reports another schema version, startup must report that problem rather than silently falling back to `metadata.sqlite3`. Likewise, an invalid recognised historical cache blocks fresh-cache creation because historical state still requires explicit handling. A fresh v4 cache is appropriate only when no recognised candidate exists.

Discovery is deliberately read-only. Migration execution, interactive or non-interactive authorisation, clean-up policy, active runtime opening and terminal presentation are separate startup responsibilities built on the discovery result.

### Startup migration authorisation policy

Cache discovery and migration authorisation remain separate stages. A complete current cache is immediately eligible for ordinary work, while a valid historical cache produces a migration requirement that must be resolved before cache-backed query or acquisition work begins. The authorisation decision itself does not execute migration, perform cut-over, delete either database or render migration progress.

Interactive startup is defined conservatively: both the input stream and the stream carrying the prompt must be terminals. In that case Discover explains the historical source, required schema transition and separate verified destination, then requires an explicit affirmative `y` or `yes`. Empty input, end-of-file and every other answer decline migration. A declined migration does not permit ordinary work to continue against the historical cache.

Non-interactive startup never prompts or reads standard input. A supported mandatory migration is automatically authorised under the documented default policy so existing scripts do not hang or acquire a new mandatory confirmation flag merely because a host first encounters the v4 transition. Automatic authorisation changes only whether the supported migration may begin; it does not weaken discovery, integrity, disk-space, certification or cut-over safety checks.

A blocked discovery result is never converted into a migration prompt. Corrupt, incomplete, structurally invalid and version-mismatched recognised candidates remain blocked, preserving the rule that authorisation cannot turn an unsafe candidate into an eligible cache.

### Verified startup cut-over and runtime adoption

Authorised startup migration now runs as a gate before cache-backed Discover work. The certified v3-to-v4 transition writes the versioned destination and permanent JSON Lines migration log, then startup performs a fresh discovery pass and requires the destination to resolve as the complete active v4 cache before any destructive source cleanup occurs. A migration result alone is not sufficient evidence for cut-over.

The default successful policy removes the superseded v3 database only after that verified active-cache resolution. `--keep-old-cache` retains the v3 source when an operator wants a post-cut-over copy. Failed or interrupted destinations are disposable by default because the accepted migration contract is restart-by-disposal rather than resume; `--keep-failed-cache-migration` preserves that destination for diagnostics. The migration log is retained in either case.

A fresh cache family now creates `metadata-v4.sqlite3` directly as a complete v4 database. The ordinary `MetadataCache` runtime recognises complete schema-v4 databases without recreating removed v3 tables, reads registered yt-dlp scalars and supported collections, and writes metadata and source state through the v4 stores. The legacy v3 runtime path remains available only where historical migration and explicit non-versioned compatibility paths still require it.

Normal cache-backed execution resolves startup first and then continues the same parsed Discover invocation with the selected v4 path. Cache status and compaction use the same startup gate when operating on the recognised versioned cache family. Syntax-only and cache-disabled operations do not trigger migration merely by starting the program.

The managed/default cache family and an explicitly supplied `--cache FILE` are deliberately different contracts. Automatic version discovery and migration apply only to the managed cache location selected by Discover. An explicit cache path remains a direct single-file request even when its basename matches a recognised managed-cache filename; startup must not infer permission to inspect, migrate or delete sibling files merely from that basename.

Managed startup is serialised across processes. Discovery occurs while holding the cache-family startup lock so a process that waits for another process to finish migration re-resolves the committed state instead of acting on a stale migration decision. This prevents concurrent invocations from racing creation, migration, certification or cut-over of the same cache family.

The test suite has a stronger isolation boundary: every test receives an isolated default XDG cache root, inherited by child processes. Tests must never discover, read, migrate, certify, create, delete or otherwise influence the user's real cache unless a test explicitly opts into a controlled fixture path. Migration tests exercise the managed lifecycle only inside their temporary cache family; unrelated acquisition, planner and presentation tests cannot reach ambient production cache state.

### Startup migration presentation

The startup migration console is a presentation consumer of the same structured migration events used by the permanent migration log. It does not inspect migration internals, change workflow state or introduce a second progress model. Implementation phase names are mapped onto stable user-facing stages: preflight, migration, indexing, verification and cut-over.

The compatibility presentation is deliberately ASCII and line-oriented. Redirected stderr and terminals where Unicode presentation is disabled use this deterministic form, showing the migration source and destination, stage transitions, bounded batch progress, verification and the final active-cache cut-over. Repeated batch events are throttled by progress percentage so large migrations do not produce unbounded output, and migration presentation never writes to machine-readable stdout.

Interactive terminals use the same console capability policy as Discover's explain presentation. When Unicode is available, migration output adds box-drawing hierarchy, explicit textual status markers and bounded progress bars. Semantic ANSI colour strengthens headings and RUN, OK, STOP and FAIL states when colour is enabled, but no state depends on colour alone. `NO_COLOR` disables colour in automatic mode while retaining Unicode structure where the terminal supports it. `--colour auto|always|never` and `--unicode auto|always|never` provide the same explicit overrides for migration and explain presentation.

Failure presentation states that the protected v3 source remains unchanged, whether an incomplete v4 destination was discarded or retained for diagnostics, where the permanent migration log was written and that restart begins the migration again rather than resuming an incomplete destination. Successful presentation identifies the active v4 cache and whether the old v3 source was removed or explicitly retained.

Both renderers consume the same structured event model and apply the same bounded progress policy, so presentation capability cannot change migration semantics. ASCII/no-colour output remains the compatibility, redirected-output and accessibility fallback even as the richer terminal renderer evolves.

## Migration storage construction

The v3-to-v4 migration builds a fresh v4 destination while keeping the v3 source read-only and separate. It does not copy the complete v3 SQLite database into the destination and later drop the legacy runtime tables. Source-state rows and detailed metadata are translated directly into the v4 representation. This avoids retaining a large freelist composed of pages formerly occupied by copied v3 tables.

During construction the destination remains explicitly incomplete and retains the historical source schema-version marker until target validation and certification succeed. Finalisation changes the destination to schema v4 and complete only after certification, preserving the restart-by-disposal and verified cut-over contract.

Issue #135 migration measurements attribute the former persistent freelist to legacy-table removal rather than metadata batching or deferred index construction. Fresh-destination construction therefore prevents the measured churn at its source. Production migration does not run `VACUUM`; the reconciliation benchmark may compact its generated destination after measurement to quantify any residual SQLite page-layout difference.
