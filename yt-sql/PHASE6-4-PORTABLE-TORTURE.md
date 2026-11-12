# Phase 6.4: Portable torture corpus

The normative corpus now includes 283 committed lexical-stress cases under `cases/torture-portable/`. Each case has an ordinary `query.ysql`, `test.json` and `expected.json`, so the existing Python, Rust and future adapters consume it without running a Python generator. Each case also has `provenance.json` identifying its approved source case, original query SHA-256, deterministic seed, generator version and transformation. The expected result is copied byte-for-byte from the independently approved source case, not obtained from an implementation under test.

`python yt-sql/materialise_torture.py --check` verifies reproducibility and detects missing, modified or stale materialised fixtures. Running without `--check` regenerates the committed fixtures for human review. The former `torture_metamorphic.py` remains an optional authoring/development stress tool, not a required portable test runner. Normative execution is through `run_conformance.py` and the implementation adapters.

This is lexical perturbation coverage only. It does not establish exhaustive grammar-aware fuzzing, malformed-query diagnosis, minimisation, or adversarial relational coverage. Those remain Phase 6.4 obligations before Phase 6 certification. A passing generated case is not proof of independently adjudicated semantics beyond the original reviewed case.

The SQLFluff canonical-formatting and lint checks intentionally exclude `torture-portable` queries because their non-canonical whitespace and keyword case are the test stimulus. The authoritative parser and execution adapters still process every materialised case; the formatter's canonical-layout contract continues to apply to the original normative cases.
