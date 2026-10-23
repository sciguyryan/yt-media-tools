# yt-media-tools

`yt-media-tools` is a pair of command-line tools built around `yt-dlp`:

- `yt-discover.py` 0.32.0 discovers, caches, queries and reports media metadata using the yt-sql query language.
- `yt-download.py` 1.23.0 downloads direct targets, discovered IDs and batch files using a predictable yt-dlp policy and versioned JSON profiles.

The tools remain independently useful, but are deliberately designed to compose through standard input and standard output:

```bash
./yt-discover.py   "SELECT id FROM @SomeChannel WHERE upload_date >= TODAY()-6mo ORDER BY upload_date ASC" | ./yt-download.py -
```

## Repository organisation

Python and Rust are maintained as independent implementations in `python/` and `rust/`. The root command-line scripts remain compatibility entry points. The shared SQLite statement library is in `common/sqlite/`, separate from the future root `yt-sql/` yt-sql conformance corpus. See [shared SQLite guidance](common/sqlite/README.md) and [the restructuring roadmap](docs/RESTRUCTURE-AND-CONFORMANCE-ROADMAP.md).

## Repository layout

```text
python/                           Python implementation, tests and benchmarks
rust/                             Rust workspace and tests
common/sqlite/                    Canonical SQLite statements and SQLFluff requirements
yt-discover.py                    Root Discover compatibility launcher
yt-download.py                    Root Downloader compatibility launcher
run-tests.py                      Unified Python and Rust test runner
defaults.json                     Shared Downloader defaults
docs/                             Tool documentation, changelogs and project notes
yt-sql/                           Shared yt-sql conformance corpus (not yet created)
```

`common/sqlite/statements/` is the single maintained source for extracted SQLite queries. The Python adapter loads those resources directly. SQLite schema ownership, connection configuration, transactions and migration finalisation remain with their respective tools.

## Requirements

Both tools require Python 3. `yt-dlp` is required for live acquisition or downloading. Discover can additionally use Node.js and YouTube.js for bounded channel acquisition when the optional adapter is installed.

See `docs/DISCOVER-README.md` and `docs/DOWNLOADER-README.md` for tool-specific requirements and usage.

## Testing

Run all available Python and Rust test suites from the repository root:

```bash
./run-tests.py
```

Select individual suites with `./run-tests.py --python` or `./run-tests.py --rust`. Both run by default, and `./run-tests.py --list` shows the available suites without running tests. Python continues to use three pytest-xdist workers with dynamic load scheduling, while Rust uses `cargo test --workspace` from `rust/`. Each suite runs even if the preceding suite fails, and the combined runner exits unsuccessfully if any selected suite fails. Use `--fail-fast` to stop at the first failing suite.

Install Python test dependencies using:

```bash
python -m pip install -r python/requirements-test.txt
```

For serial Python execution, use `./run-tests.py --python --serial`. Additional pytest arguments are forwarded to the Python suite, for example `./run-tests.py --python --durations=25`. To run only Rust tests, Cargo and the toolchain specified by `rust/rust-toolchain.toml` must be available.

Routine testing excludes the `scale` and `stress` tiers. Run selected large-dataset tests with:

```bash
python -m pytest -m scale
```

Run huge torture/scalability tests with:

```bash
python -m pytest -m stress
```

Run both non-routine tiers explicitly with:

```bash
python -m pytest -m "scale or stress"
```

Ruff is configured for repository linting and formatting, and both checks run in GitHub Actions. Performance benchmarks are opt-in and documented in `docs/PERFORMANCE.md`; CI runs only a small non-comparative benchmark smoke check because shared runners are not treated as stable performance targets.

For SQLite SQL quality checks, see [the SQLFluff setup and commands](common/sqlite/README.md).

## Versioning

The two command-line applications retain independent versions because they evolve at different rates. Release history is recorded independently in `docs/DISCOVER-CHANGELOG.md` and `docs/DOWNLOADER-CHANGELOG.md`.

## Common table expressions

Discover supports non-recursive yt-sql `WITH` CTEs plus positional `UNION` and `UNION ALL`, including composition across independently acquired yt-dlp sources. See `docs/DISCOVER-README.md` and `docs/YT-SQL.md` for the execution, schema-reconciliation and scoping contracts.

## Documentation linting

GitHub Actions runs pinned `markdownlint-cli2` checks for the project Markdown. The initial CI policy enforces MD001 heading increments and MD012 consecutive blank lines through `.markdownlint-cli2.jsonc`. For a project-local installation, run `npm install` once and then `npm run lint:markdown`; the shared configuration excludes `node_modules/**`.

## Future work

The longer-term programmes are documented under `docs/`, with active Discover version-series plans under `docs/roadmap/`. Completed Discover series are retained in release history and durable architecture documentation rather than the active roadmap directory. Discover 0.32.0 adds grammar-revision-2 derived relations, line comments and base-aware row slicing while retaining the hand-written parser after the completed replacement investigation. Downloader 1.23.0 adds collection-aware acquisition on top of the established machine-interface foundation.

## External tool diagnostics

Both tools can report the external operations they invoke with `--debug-external`. Diagnostics are written to standard error and redact credential-bearing arguments by default. `--debug-external-unsafe` deliberately disables redaction for local troubleshooting and may expose cookies, credentials or other sensitive values in terminal history or captured logs. Command integrations are rendered as their final argument vector, while bridge and library integrations may report an annotated operation and meaningful arguments instead of pretending to have a command line.

## Source layout

The Python implementation, tests, benchmarks and yt-dlp plugin live under `python/`. The Rust implementation remains under `rust/`. The existing root commands `./yt-discover.py` and `./yt-download.py` are retained as compatibility launchers; their implementations have moved, but command-line invocation does not need to change. The root test and benchmark commands also forward to their Python implementations.
