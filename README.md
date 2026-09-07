# YouTube downloader

The repository now also contains the experimental `yt-discover.py` companion. See `DISCOVER-README.md` for its current usage.

`yt-download.py` is a small wrapper around `yt-dlp` for the download settings I use most often.

## Requirements

- Python 3.10 or later.
- `yt-dlp` available in `PATH`.
- FFmpeg for formats and post-processing that require it.

## Basic use

Download one or more videos directly:

```bash
./yt-download.py VIDEO_URL
./yt-download.py VIDEO_URL ANOTHER_VIDEO_URL
```

With no targets, the downloader reads IDs from `ids.txt`:

```bash
./yt-download.py
```

A single positional argument that names an existing local file is treated as a batch file. You can also select one explicitly with `--input-file`:

```bash
./yt-download.py ./more-ids.txt
./yt-download.py --input-file ./more-ids.txt
```

Read targets from standard input by using `-` as a target:

```bash
printf '%s\n' VIDEO_ID ANOTHER_VIDEO_ID | ./yt-download.py -
```

Blank lines and lines beginning with `#` are ignored when reading standard input.

Preview the generated `yt-dlp` command without running it:

```bash
./yt-download.py --dry-run VIDEO_URL
```

## Profiles

Profiles keep commonly used settings together. The built-in profiles are stored in `profiles/`.

Use the default profile:

```bash
./yt-download.py VIDEO_URL
```

Use the playlist profile:

```bash
./yt-download.py --profile playlist PLAYLIST_URL
```

You can also pass a profile file directly:

```bash
./yt-download.py --profile ./my-profile VIDEO_URL
```

Profile files begin with `@profile`, followed by `key=value` settings. Blank lines and lines beginning with `#` are ignored.

Supported settings are:

- `path`
- `output`

Profiles control presentation only. Resolution, rate limiting, cookies, archive handling, batch input and playlist direction are application or command-line policy.

Before a real download, the downloader checks that the configured cookies file exists. It also rejects an archive path that already exists as something other than a file and an output path that already exists as something other than a directory. Dry-run mode does not require those runtime paths to exist.

## Batch-file maintenance

When a batch file is being used as a persistent queue, completed IDs can be removed after a download run:

```bash
./yt-download.py --remove-completed-ids
```

The downloader reconciles a file-backed queue with the configured yt-dlp archive before starting a download and again after a successful run. Only lines whose complete stripped value exactly matches an archived video ID are removed. Comments, blank lines, URLs and unrelated queue content are preserved.

## Download policy

The default rate limit is now `20M`, correcting the much lower value carried over from the first Python rewrite. Resolution validation accepts any positive numeric height rather than a fixed built-in list.

`--rev` is available as a shorter alias for `--playlist-reverse`.

## Other options

Run the built-in help for the complete option list:

```bash
./yt-download.py --help
```

## Licence

These tools are distributed under the GNU Lesser General Public License version 2.1. See `LICENSE` for the licence text.

## Profile discovery and fallback

The downloader can now list the profiles installed beside the script:

```bash
./yt-download.py --list-profiles
```

Named profiles are still simple `key=value` files. Duplicate keys and empty keys are now rejected with a file and line number.

If a named built-in profile does not exist, the downloader warns and falls back to `default`. An explicit profile path remains strict and must exist. This is still the older policy-heavy profile model; later releases will narrow profiles to output presentation.

## Formal output-profile format

Output profiles now begin with an explicit format marker:

```text
@profile
path=/mnt/storage/Downloads/YouTube/
output=%(title)s [%(id)s] [%(uploader)s].%(ext)s
```

`@profile` now identifies a downloader profile rather than being merely tolerated text. A profile may define `path`, `output`, or both, and no other keys are accepted.

`path` controls the output location and `output` controls the yt-dlp filename/template layout. Missing named profiles still fall back to `default`. Existing malformed profiles remain configuration errors.

## Downloader 1.0

Version 1.0 marks the point where the Python downloader interface is treated as stable enough for ordinary use.

Profiles are script-relative and use the formal `@profile` format. They control output path and filename layout only. Resolution, rate limiting, cookies, archive handling and other operational policy remain application or CLI concerns.

The established direct-target, `--input-file`, positional batch-file and standard-input modes remain supported. `--examples` provides practical invocations for common input, playlist, profile and dry-run use.

## Automated tests

The project now has a small pytest suite covering selected Discover query/cache invariants and downloader profile/input behaviour.

```bash
python -m pytest
```

This is the beginning of automated regression testing rather than a claim of complete coverage. Manual end-to-end checks remain important, especially for live yt-dlp and YouTube.js acquisition.

## Downloader 1.1

Queue maintenance is now deliberately conservative. Archive reconciliation ignores malformed single-field archive records, removes only exact ID lines from file-backed queues, and preserves unrelated queue bytes.

`--remove-completed-ids` is rejected for direct positional targets because there is no persistent queue file to update.

## Ruff maintenance release

This release applies the first substantive Ruff-driven cleanup after local Ruff adoption.

Date parsing now produces timezone-aware UTC datetimes where a datetime object is required, filter branches are simplified without changing their conditions, and unexpected YouTube.js bridge result types raise `TypeError`.

The automated test suite remains the primary behavioural regression check. Ruff is still being used locally without a committed repository configuration in this release.

## Ruff configuration

The repository now carries its local Ruff configuration in `ruff.toml`.

Check the project with:

```bash
ruff check .
ruff format --check .
```

Apply safe automatic lint fixes and formatting during local development with:

```bash
ruff check --fix .
ruff format .
```

The repository configuration is now the shared definition for local Ruff checks. GitHub Actions integration is not present yet.

## Ruff in GitHub Actions

GitHub Actions now runs Ruff on pushes and pull requests using the repository `ruff.toml`.

The workflow is deliberately check-only:

```bash
ruff check .
ruff format --check .
```

CI never runs `ruff check --fix` or `ruff format`, so repository changes remain an explicit local development action.

## Downloader 1.3

Downloader input handling now resolves direct targets, standard input and file-backed queues into an explicit `InputSource` model before command construction. The older `resolve_targets()` interface remains as a compatibility wrapper during this transition.

The yt-dlp runtime policy has also been brought closer to the intended stable behaviour. It now embeds chapters and subtitles, preserves modification times, removes SponsorBlock segments, enables audio and video multistreams, uses a dedicated temporary path, sorts formats by the requested resolution and supplies the selected YouTube player-client extractor arguments.

## Downloader 1.4

Completed-ID queue maintenance now happens per download through yt-dlp's `after_move` execution hook. When `--remove-completed-ids` is active for a file-backed queue, yt-dlp invokes a hidden downloader completion handler with the completed video ID after the final file move.

The handler removes only the first exact matching ID line and preserves unrelated queue bytes. Pre-run archive reconciliation remains as a conservative recovery mechanism for IDs already present in the archive before the current run.

Whole-run post-download archive reconciliation is no longer the primary completion mechanism.

## Downloader 1.4.1

This patch hardens the per-item queue update path introduced in 1.4.0. Exact ID removal now operates directly on bytes, preserves the queue file mode and flushes the temporary replacement before the atomic rename.

Runtime paths are centralised as script-relative constants for profiles, the default archive, cookies and ID queue. The temporary download path remains `/mnt/storage/Temp/yt-dlp`.

Dry-run command construction remains suitable for inspecting configuration without requiring a runnable download environment.
