# yt-discover cache v4 design

The cache-size problem started this discussion. A real Discover database can grow to several gigabytes, and v3 gives us a fairly obvious suspect: `metadata_records` stores the complete yt-dlp JSON response for each `(source_url, video_id)`. If the same video turns up through several sources, we can store the whole thing several times. Formats, signed URLs, storyboards, headers and other backend baggage then sit there because `raw_json` is the authoritative record, whether yt-sql ever asks for them again or not.

That looked at first like a pruning job. It isn't. Once `raw_json` stops being the centre of the cache, we have to answer who owns a metadata value, what the identity of the media actually is, how two providers supplying `duration` interact, what "not acquired" means without a JSON blob to inspect, and what happens to source coverage when metadata is thrown away. There is also a multi-gigabyte v3 database to get across the boundary safely. That last part is where this gets uncomfortable: an elegant v4 is not much use if upgrading to it can destroy or silently reinterpret the cache people already have.

This is the record of where we landed. It is not the v4 schema definition yet. A few table shapes and CLI details are intentionally still open because the current tree needs a more mechanical audit before choosing them.

## The v3 shape we are leaving

The detailed record today is:

```text
metadata_records(source_url, video_id, fetched_at, raw_json)
```

`raw_json` is described by the cache code as authoritative yt-dlp JSON. Freshness is layered over the one `fetched_at`: different fields have different maximum ages, and a `raw.*` request also checks that the nested path is present. That is better than treating the whole blob as equally fresh, but it still means one acquisition time is standing in for a potentially large set of observations.

Source knowledge is already separate. `source_observations`, `source_entries`, `source_coverage` and `source_frontiers` carry membership, ordering and completeness/frontier information. The existing code is careful not to turn a mere observation into a trusted frontier. Keep that distinction. We spent too much effort getting incremental source behaviour right to blur it during a storage refactor.

The current SQLite connection uses foreign keys, WAL and `synchronous=NORMAL`. Those are facts about v3, not recommendations for the migration writer. We need measurements before choosing bulk-migration pragmas or a compaction strategy.

There are two wrinkles that would be easy to miss if we only looked at the database tables. Specialised YouTube.js and ytmusicapi acquisitions can currently supply a small exact-scalar set, but those specialised results are deliberately not persisted. v4 gives us a chance to fix that rather than treating extension providers as second-class cache citizens.

The other wrinkle is `raw.*`. It is real yt-sql surface, not a debug trick. Parser, schema inference, member/collection behaviour, evaluator, planner, examples and tests know about it. Removing `raw_json` therefore creates a language compatibility problem. We should call it that instead of letting a database migration accidentally decide the fate of a query feature.

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

There is no automatic age-based deletion by default. Users who opt into retention can have opportunistic/throttled maintenance, but it should call the same pruning machinery as an explicit maintenance command. Compaction remains explicit; running a heavyweight `VACUUM` because a query happened to trigger retention would be surprising and potentially very expensive.

We rejected `last_queried_at` as a retention signal. "Queried" gets murky once planners, failed predicates and partial acquisitions are involved, and turning reads into writes for this purpose is unattractive. Retention is based on successful acquisition/refresh and source enumeration instead.

Explicit pruning should be previewable. The preview and execution ought to come from the same internal plan so the dry run is not a second approximation of the deletion logic. Useful output includes provider-record counts, source/facet state affected, identities that would become orphaned and the distinction between logical data removed and disk space that compaction might later reclaim.

For a large destructive operation an interactive `[y/N]` is sensible. Non-interactive use cannot sit waiting for a terminal that is not there; explicit authorisation will be needed when a configured threshold is crossed. Automatic retention is already authorised by configuration and therefore cannot prompt.

Command names and destructive-operation thresholds remain a maintenance-surface decision. They should be derived from the existing cache CLI/config conventions when that surface is implemented rather than being invented in this schema document.

## Cache status should explain what is on disk

Once provider schemas and maintenance exist, a useful status command becomes more important than it is today. At a minimum we will want cache schema/version, provider registrations/revisions, entity/provider-record counts, acquisition/source-state summaries, configured retention, stale/unavailable-provider information and SQLite file/free-page/WAL information. Verbose output can go deeper.

Long operations such as migration, pruning verification and compaction should share progress/event plumbing. Normal mode needs enough progress to prove a multi-hour operation is alive. Verbose can add provider/table counters and timings. Debug remains implementation detail under the existing debug contract. Per-record chatter would make the useful messages disappear.

## `raw.*` needs an actual decision

v4 should not keep an arbitrary backend blob merely so `raw.foo.bar` can continue reaching into it. That would preserve the largest part of the problem we are trying to solve.

The replacement is registration: useful data becomes a field with a type, provider, acquisition behaviour and freshness. Dynamic extensions still work, but they register meaning instead of exposing the shape of an upstream response.

The completed raw-metadata audit separates recognised scalar metadata, stable logical collections and genuinely dynamic compatibility material. Recognised scalars are registered and persisted through the provider model. Stable collections retain their established logical contracts while first-class v4 collection storage remains separate work. Genuinely dynamic nested material is retained only in the reduced source-scoped compatibility payload.

Simple stable scalar `raw.*` spellings resolve through canonical metadata and no longer force open-ended dynamic acquisition. Nested and structured dynamic paths retain the compatibility path. No provider-specific namespace syntax has been introduced.

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

A transition roughly does this: validate the source; detect/apply its known pre-transition fixes to controlled migration state; run its phases; validate the target; return a successful database only at the end. Fixes should be independently testable, including already-fixed and unfixable cases.

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

Non-interactive authorisation remains a startup/CLI policy decision. A script cannot hang on a prompt, so the migration surface must either have documented non-interactive defaults or require explicit authorisation. This document deliberately does not invent that CLI policy.

## Current implementation boundary

The field/type inventory, v3 validity contract and historical fixture/oracle, provider registry, v4 entity metadata, source/facet persistence, registered scalar replacement and reduced `raw.*` compatibility representation are now implemented foundations.

Remaining cache-v4 work belongs to later maintenance, migration and startup/cut-over issues. That includes first-class storage for stable collections where required, cache maintenance and pruning surfaces, migration execution and verification policy, cache selection/startup behaviour, and realistic migration/retention benchmarking. The accepted v3 contract remains the migration source oracle until that wider cut-over is complete.

### Transitional source-state integration

The v3 source-state tables remain part of the live Discover cache while the wider cache-v4 acquisition cut-over is incomplete. Opening the cache imports existing source observations, ordered entries, coverage claims and trusted frontiers into the v4 entity-backed representation. The import is idempotent and does not promote an observation into coverage or frontier trust.

During this compatibility period, source-state mutations are mirrored into v4. Provider metadata may therefore be pruned and reacquired without erasing enumeration knowledge or requiring the source to be enumerated again. The legacy source-state tables can be retired only as part of the wider runtime cut-over once no supported path depends on them.
