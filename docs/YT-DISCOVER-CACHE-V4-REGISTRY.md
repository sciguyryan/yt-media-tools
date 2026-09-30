# yt-discover cache v4 provider registry

Issue #127 starts by fixing the code-owned vocabulary before the SQLite registry is allowed to make it persistent. This document records that boundary. It is deliberately not the v4 database schema.

A provider definition has a stable textual key, an independently versioned provider schema revision, a provider-owned metadata table identity, named acquisition groups, logical field claims and applicability. Field claims use the existing yt-sql `QueryType` model rather than creating a cache-specific type system. They also name the provider storage field and carry a default freshness policy.

Freshness has three code-level forms: a positive maximum age, immutable until explicit invalidation, and always refresh. These are defaults. Persistent configuration and overrides belong to the database side of the registry in #127 Part 2.

Acquisition groups describe real provider fetch boundaries. A field must name a group declared by its provider. The declaration does not yet say that every successful acquisition of that group establishes value-or-NULL for every member. That distinction depends on the acquisition-state work in #128 and must not be invented here.

Applicability records stable semantic constraints such as content service, logical source kind, facet and required source traits. It does not replace the existing physical provider-selection machinery. The two contracts can be reconciled as the v4 implementation moves into acquisition and persistence, but this part does not change current provider selection.

Provider priority, enabled state, immutable registration order and user overrides are intentionally absent from the code-owned definition. They are persistent deployment state. SQLite stores and reconciles that state with the code-owned contract.

Likewise, this part does not create `entity_id`, provider metadata rows or acquisition-state rows, and it does not resolve competing cached values. Those are #128 concerns. The purpose here is to give those later layers a small, validated vocabulary instead of letting table columns become the language contract by accident.

## Persistent registry state

Part 2 gives the registry a persistent half without making it the active cache implementation. SQLite now owns compact provider, acquisition-group and field identities, append-only registration order, provider enablement and priority, and per-field priority and freshness overrides.

Reconciliation starts from the installed code declaration. A provider seen for the first time is appended to the persistent registry. Reopening the same database preserves its existing identities and registration order even if installed declarations are presented in a different order. A provider that is no longer installed remains registered; absence of an implementation is not a request to delete its historical identity or configuration.

The stored rows also retain a snapshot of the provider contract needed to recognise incompatible reuse of an existing identity. Metadata-table identity, field storage identity, field type and acquisition-group membership are not silently rewritten. A provider schema revision may advance, but an older implementation cannot open a database whose recorded provider revision is newer. Changes that require a real provider migration therefore remain explicit work rather than reconciliation side effects.

Freshness defaults are code-owned and may evolve with a provider revision. Deployment choices remain database-owned. Reconciliation updates the default while retaining any field-specific override. Provider enabled state and priority behave the same way: reopening or reinstalling a provider does not reset them.

These tables are deliberately isolated from the v3 runtime cache path. Part 2 establishes persistent registry behaviour for v4; it does not select a v4 database at startup, migrate a v3 database, create entity metadata, record acquisition state or resolve competing cached values.

## Field-provider resolution metadata

Part 3 makes provider precedence queryable without crossing into entity-value resolution. For a logical field, the registry can now return the enabled providers whose implementations are currently available, together with the provider and field identities, yt-sql type, acquisition group, effective priority and effective freshness policy.

Effective priority is the field override when one exists and otherwise the provider priority. Candidates are ordered by effective priority descending and then by the provider's immutable persistent registration order ascending. Equal priorities are therefore deterministic across reopen and independent of the order in which installed provider declarations are presented.

Implementation availability is supplied separately from persistent registration. A provider can remain registered, configured and historically identifiable while its implementation is absent. Disabled and unavailable providers do not appear in the active candidate list, but neither condition deletes their registry state.

Providers may claim the same logical field only when they agree on its yt-sql type. Reconciliation rejects incompatible shared-field claims transactionally. This is a semantic compatibility check on the logical field contract, not a declaration that provider storage layouts or acquisition mechanisms are interchangeable.

The candidate list is planning metadata. It does not inspect entity observations, acquisition state, SQL NULL, failure state or observation freshness. Consequently it does not choose the winning cached value for an entity. Dynamic value resolution remains #128 work.

## Registry lifecycle and #128 hand-off

Part 4 makes declaration lifecycle explicit. Reconciliation marks providers, acquisition groups and fields as currently declared only when the installed code contract still contains them. Removing an implementation or field does not delete its persistent identity, registration order or database-owned policy. Reinstalling or re-adding the same compatible declaration recovers that history.

Historical declarations do not participate in active shared-field compatibility or field-provider candidate planning. Current declarations still cannot reuse a stable provider or field identity incompatibly. Provider schema revisions move forwards only, and incompatible reconciliation remains transactional.

This completes the registry boundary for #127. The registry can now answer which currently declared, enabled and available providers claim a logical field; whether those claims agree on the yt-sql type; their persistent precedence; their acquisition group; and their effective freshness policy. It still cannot answer whether an entity has a value, known SQL NULL, not-acquired state, failure, inapplicability or stale observation. It also cannot choose a value from provider observations. Those are the storage and resolution responsibilities of #128.

The #128 implementation should consume registry identities and candidate metadata rather than duplicating precedence or field-contract rules. Entity and provider observation tables should reference the compact persistent identities established here, while acquisition-state semantics remain separate from registry declaration state.

## #128 entity-storage hand-off

Issue #128 Part 1 now consumes the registry identities without extending their meaning. Cache-v4 media identity is `(service, external_id)` with a compact integer `entity_id`, so one service-owned item can be referenced by several logical sources without duplicating provider metadata. The same external identifier on another service remains a different entity.

Each declared provider owns its metadata table and keys rows by `entity_id`. Scalar columns are derived from the provider's registered storage names and yt-sql types. Adding a compatible scalar field at a later provider schema revision appends its column without rebuilding existing rows. Removed historical columns may remain physically present, while the registry declaration continues to determine which fields are semantically active.

Part 1 deliberately does not infer observation state from a provider row or column. A NULL column is not proof of known SQL NULL. Part 2 adds acquisition-group state keyed by `(entity_id, provider_id, acquisition_group_id)`: no state row means the group has not yet been acquired, a successful attempt records the last successful resolution time, and a failed refresh records the failed attempt without erasing an earlier success. Part 3 derives scalar field observation state from that history, the provider contract, applicability, the stored value and effective freshness policy. A failed refresh after an earlier success remains visible as an acquisition fact without erasing or automatically staling the earlier observation. Part 4 completes #128's scalar resolution boundary by consuming the registry's effective priority and registration order, continuing past known NULL in search of a fresh value, and retaining stale observations only as unresolved fallback state.

Structured and collection fields are not serialised into a generic JSON or TEXT escape hatch. They require an explicit provider storage mapping before they can be persisted in v4. This keeps the query-material-only boundary intact while the field inventory determines which relational shapes are actually required.
