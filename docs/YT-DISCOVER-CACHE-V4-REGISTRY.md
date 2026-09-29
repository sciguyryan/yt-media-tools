# yt-discover cache v4 provider registry

Issue #127 starts by fixing the code-owned vocabulary before the SQLite registry is allowed to make it persistent. This document records that boundary. It is deliberately not the v4 database schema.

A provider definition has a stable textual key, an independently versioned provider schema revision, a provider-owned metadata table identity, named acquisition groups, logical field claims and applicability. Field claims use the existing yt-sql `QueryType` model rather than creating a cache-specific type system. They also name the provider storage field and carry a default freshness policy.

Freshness has three code-level forms: a positive maximum age, immutable until explicit invalidation, and always refresh. These are defaults. Persistent configuration and overrides belong to the database side of the registry in #127 Part 2.

Acquisition groups describe real provider fetch boundaries. A field must name a group declared by its provider. The declaration does not yet say that every successful acquisition of that group establishes value-or-NULL for every member. That distinction depends on the acquisition-state work in #128 and must not be invented here.

Applicability records stable semantic constraints such as content service, logical source kind, facet and required source traits. It does not replace the existing physical provider-selection machinery. The two contracts can be reconciled as the v4 implementation moves into acquisition and persistence, but this part does not change current provider selection.

Provider priority, enabled state, immutable registration order and user overrides are intentionally absent from the code-owned definition. They are persistent deployment state. Part 2 will define how SQLite stores and reconciles that state with the code-owned contract.

Likewise, this part does not create `entity_id`, provider metadata rows or acquisition-state rows, and it does not resolve competing cached values. Those are #128 concerns. The purpose here is to give those later layers a small, validated vocabulary instead of letting table columns become the language contract by accident.

## Persistent registry state

Part 2 gives the registry a persistent half without making it the active cache implementation. SQLite now owns compact provider, acquisition-group and field identities, append-only registration order, provider enablement and priority, and per-field priority and freshness overrides.

Reconciliation starts from the installed code declaration. A provider seen for the first time is appended to the persistent registry. Reopening the same database preserves its existing identities and registration order even if installed declarations are presented in a different order. A provider that is no longer installed remains registered; absence of an implementation is not a request to delete its historical identity or configuration.

The stored rows also retain a snapshot of the provider contract needed to recognise incompatible reuse of an existing identity. Metadata-table identity, field storage identity, field type and acquisition-group membership are not silently rewritten. A provider schema revision may advance, but an older implementation cannot open a database whose recorded provider revision is newer. Changes that require a real provider migration therefore remain explicit work rather than reconciliation side effects.

Freshness defaults are code-owned and may evolve with a provider revision. Deployment choices remain database-owned. Reconciliation updates the default while retaining any field-specific override. Provider enabled state and priority behave the same way: reopening or reinstalling a provider does not reset them.

These tables are deliberately isolated from the v3 runtime cache path. Part 2 establishes persistent registry behaviour for v4; it does not select a v4 database at startup, migrate a v3 database, create entity metadata, record acquisition state or resolve competing cached values.
