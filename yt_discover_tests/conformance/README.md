# yt-sql conformance architecture

The yt-sql conformance suite compares the production query engine with an independently authored Python semantic oracle over deterministic generated metadata. The generator, oracle, and production query engine have deliberately separate responsibilities.

## Test lifecycle

Normal pytest execution requires no pre-generated corpus. A test requests the smallest useful profile through a fixture. The harness reports generation progress, creates the logical records and a real temporary yt-discover SQLite cache, runs the oracle and yt-sql paths independently, compares their results, reuses the generated profile for the rest of the pytest session, and leaves cleanup to pytest's temporary-directory lifecycle.

The standard profiles are defined centrally in `generate_dataset.py`:

```text
small       36 records
normal   1,000 records
large   10,000 records
huge   100,000 records
```

Use `small` for focused semantic and boundary cases, `normal` for broader interaction coverage, `large` for scaling-sensitive operations, and `huge` for torture, scalability, and future performance work. Tests may request an exact custom size when no named profile is appropriate.

The default automated test suite generates only the `small` and `normal` profiles. `large` and `huge` remain available for deliberate manual stress, scalability, and performance runs, but are disabled in routine pytest execution to keep local and CI validation practical.

## Reproducibility contract

A logical dataset is identified by generator version, seed, and requested size. For the same generator version and seed, a smaller dataset is an exact prefix of every larger dataset. This makes failures reproducible and permits direct comparisons between scales without changing the records already present at smaller scales.

The default seed is `31415926`. Generated payloads record the generator version, seed, profile, record count, and a SHA-256 digest of the logical record sequence.

## Oracle independence

`oracle.py` is deliberately not a second yt-sql parser. Test authors write the yt-sql text and its intended Python semantics separately. The oracle uses a small LINQ-style chain over ordinary Python records. Operators include filtering, projection, distinctness, ordering, skipping, and taking.

Oracle code must not import or call production query parsing, planning, evaluation, schema, metadata-normalisation, or output modules. This constraint is itself tested. A production parsing or evaluation defect must therefore disagree with the independently expressed algorithm rather than teaching the oracle to make the same mistake.

When a new yt-sql feature is added, its conformance cases should cover the direct semantics, important boundaries, NULL behaviour where applicable, ordering/tie behaviour, interactions with existing row shaping, and at least one non-trivial composition. Use larger profiles where cardinality or algorithmic scale can affect correctness.

## Manual generation

Manual generation is optional and intended for inspection, reproduction, torture tests, and future benchmarking:

```bash
python yt_discover_tests/conformance/generate_dataset.py --profile small --output-dir /tmp/yt-sql-data
python yt_discover_tests/conformance/generate_dataset.py --profile huge --output-dir /tmp/yt-sql-data
python yt_discover_tests/conformance/generate_dataset.py --size 250000 --seed 31415926 --output-dir /tmp/yt-sql-data
```

Generate all four standard profiles with:

```bash
python yt_discover_tests/conformance/generate_dataset.py --output-dir /tmp/yt-sql-data
```

Normal test runs should not use or commit the resulting files.
