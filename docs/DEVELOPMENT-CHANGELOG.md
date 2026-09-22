# Development changelog

This file records meaningful changes during active development. It is not release history. When a dot release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Discover - Capability-oriented metadata provider selection

- [maintenance] Add backend-neutral metadata requirement and provider-capability contracts covering authority, field coverage, resolved source applicability, authentication, acquisition granularity, provenance and relative physical cost.
- [maintenance] Project existing physical acquisition stages into provider requirements without changing yt-sql semantics or runtime acquisition behaviour.
- [test] Add deterministic coverage for exact authority, field coverage, source constraints, cookie requirements, cost ordering and physical-plan projection.
- [docs] Define the provider-selection boundary and its deliberate exclusions before provider benchmarks and production integration.
