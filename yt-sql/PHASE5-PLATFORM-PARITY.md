# Phase 5.1: Cross-platform conformance parity

The nine-environment Python CI matrix now has a dependent certification job. It requires all nine report artifacts, validates their versioned report contracts, verifies identical approved case sets and implementation/configuration identities, and refuses certification if **any** environment reports `fail`, `error`, `xfail` or `xpass`. Identical failures are not parity success.

The comparison intentionally uses normative conformance outcomes, not engine-generated expectations. It does not claim to establish byte-for-byte equivalence of observed values: the conformance runner checks each environment against the same independently authored JSON expectation, which is the normative authority. A matching pass therefore has a stronger meaning than matching unreviewed engine output.

The platform gate does not yet cover Rust or additional metadata backends. It cannot establish Unicode equivalence across different Unicode database versions merely by comparing pass/fail status for a limited corpus. Additional differential and metamorphic tests, more complete feature coverage, and the Phase 6 retirement audit remain outstanding. Legacy semantic tests must not be removed on the strength of this gate alone.

Run `python yt-sql/compare_platform_reports.py <report-path> <report-path> ...` with reports in uniquely named parent directories. A comparison with fewer than two independent reports is rejected. CI requires the complete matrix.
