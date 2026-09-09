# yt-media-tools

`yt-media-tools` is a pair of command-line tools built around `yt-dlp`:

- `yt-discover.py` discovers, caches, queries and reports media metadata using the yt-sql query language.
- `yt-download.py` 1.7.0 downloads direct targets, discovered IDs and batch files using a predictable yt-dlp policy and optional output profiles.

The tools remain independently useful, but are deliberately designed to compose through standard input and standard output:

```bash
./yt-discover.py   "SELECT id FROM @SomeChannel WHERE upload_date >= TODAY()-6mo ORDER BY upload_date ASC" | ./yt-download.py -
```

## Repository layout

```text
yt-discover.py
yt-download.py
yt_media_tools/        Shared/internal Python package
defaults.json          Downloader parameter profiles
profiles/              Downloader output profiles
yt_discover_tests/     Discover test suite
yt_downloader_tests/   Downloader test suite
DISCOVER-README.md     Discover documentation
DOWNLOADER-README.md   Downloader documentation
YT-SQL.md              yt-sql language reference
YT-SQL-OPTIMISATION.md yt-sql optimisation strategy
TODO.md                Accepted future work and design directions
pytest.ini             Combined test discovery configuration
```

The internal package is named `yt_media_tools`. It keeps reusable implementation separate from the command-line entry points while allowing extractor-specific adapters to remain contained.

## Requirements

Both tools require Python 3. `yt-dlp` is required for live acquisition or downloading. Discover can additionally use Node.js and YouTube.js for bounded channel acquisition when the optional adapter is installed.

See `DISCOVER-README.md` and `DOWNLOADER-README.md` for tool-specific requirements and usage.

## Testing

Run the routine suites from the repository root:

```bash
python -m pytest
```

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

Ruff is configured for repository linting and formatting, and both checks run in GitHub Actions.

## Versioning

The two command-line applications retain independent versions because they evolve at different rates. Release history is recorded in `CHANGELOG.md`.

## Common table expressions

Discover supports non-recursive yt-sql `WITH` CTEs plus positional `UNION` and `UNION ALL`, including composition across independently acquired yt-dlp sources. See `DISCOVER-README.md` and `YT-SQL.md` for the execution, schema-reconciliation and scoping contracts.

## Documentation linting

GitHub Actions runs pinned `markdownlint-cli2` checks for the project Markdown. The initial CI policy enforces MD001 heading increments and MD012 consecutive blank lines through `.markdownlint-cli2.jsonc`. For a project-local installation, run `npm install` once and then `npm run lint:markdown`; the shared configuration excludes `node_modules/**`.
