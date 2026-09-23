# Downloader development changelog

This file records meaningful Downloader changes during active development. It is not release history. When a Downloader release is completed and accepted, relevant entries are reconciled into the root `CHANGELOG.md` and the completed development section is cleared or advanced for the next work item.

## Parameter-profile option coverage

- [feature] Add typed profile and CLI support for yt-dlp impersonation targets with explicit inherited-policy removal.
- [maintenance] Classify every public CLI destination by persistence semantics so future options require an explicit profileability decision.
- [test] Cover impersonation profile validation, command compilation, override behaviour and CLI classification completeness.
- [docs] Document profileable impersonation policy and the deliberate invocation-only option classes.
