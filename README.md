# yt-media-tools

`yt-media-tools` is a pair of command-line tools built around `yt-dlp`:

- `yt-discover.py` discovers, caches, queries and reports media metadata using the yt-sql query language.
- `yt-download.py` 1.19.1 downloads direct targets, discovered IDs and batch files using a predictable yt-dlp policy and optional output profiles.

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
yt_media_tools_tests/  Shared internal-package test suite
docs/                   Project documentation
docs/DISCOVER-README.md     Discover documentation
docs/DOWNLOADER-README.md   Downloader documentation
docs/DISCOVER-FUTURE-WORK.md   Planned Discover language and capability programme
docs/DOWNLOADER-FUTURE-WORK.md Planned Downloader architecture and capability programme
docs/YT-SQL.md              yt-sql language reference
docs/YT-SQL-OPTIMISATION.md yt-sql optimisation strategy
docs/TODO.md                Accepted future work and design directions
docs/roadmap/          Living Discover version-series roadmaps
pytest.ini             Combined test discovery configuration
```

The internal package is named `yt_media_tools`. It keeps reusable implementation separate from the command-line entry points while allowing extractor-specific adapters to remain contained. Common low-level yt-dlp runtime mechanics are shared by both applications without merging their higher-level acquisition and download policies.

## Requirements

Both tools require Python 3. `yt-dlp` is required for live acquisition or downloading. Discover can additionally use Node.js and YouTube.js for bounded channel acquisition when the optional adapter is installed.

See `docs/DISCOVER-README.md` and `docs/DOWNLOADER-README.md` for tool-specific requirements and usage.

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

Discover supports non-recursive yt-sql `WITH` CTEs plus positional `UNION` and `UNION ALL`, including composition across independently acquired yt-dlp sources. See `docs/DISCOVER-README.md` and `docs/YT-SQL.md` for the execution, schema-reconciliation and scoping contracts.

## Documentation linting

GitHub Actions runs pinned `markdownlint-cli2` checks for the project Markdown. The initial CI policy enforces MD001 heading increments and MD012 consecutive blank lines through `.markdownlint-cli2.jsonc`. For a project-local installation, run `npm install` once and then `npm run lint:markdown`; the shared configuration excludes `node_modules/**`.

## Future work

The longer-term programmes are documented under `docs/`, with active Discover version-series plans under `docs/roadmap/`. Completed Discover series are retained in release history and durable architecture documentation rather than the active roadmap directory. Discover 0.29.x reviews and settles language and parser architecture before the broader feature programme resumes in 0.30.x. Downloader 1.19.1 contains the current machine-interface foundation.
