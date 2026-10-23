# Offset and limit migration proposal

Source: `python/yt_discover_tests/conformance/cases.py`, case `offset_limit`.
The SQL text is preserved exactly. The proposed expected IDs are independently calculated from the committed `python-v6-small` fixture: exclude NULL `view_count` values, sort by descending count, skip three records and retain five. **Review blocker:** the fixture has equal `view_count` values across the selected window. The proposed order follows stable source order for ties, but the SQL query does not specify a secondary ordering key. Resolve whether the expected row order is guaranteed by the language contract before admission.

This directory is **not** part of the normative `cases/` tree. Its `proposed-expected.json` is not an approved expectation and is never consumed by the permanent harness. An independent reviewer must verify the query, fixture and semantics before copying it into a case directory and applying the normal admission process. Retain the original Python oracle and tests.
