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

Profile files use one `key=value` setting per line. Blank lines and lines beginning with `#` are ignored.

Supported settings are:

- `resolution`
- `output`
- `rate_limit`
- `cookies`
- `archive`
- `batch_file`
- `playlist_reverse`

Relative paths in a profile are resolved relative to that profile file.

Command-line options override the corresponding profile settings.

Before a real download, the downloader checks that the configured cookies file exists. It also rejects an archive path that already exists as something other than a file and an output path that already exists as something other than a directory. Dry-run mode does not require those runtime paths to exist.

## Batch-file maintenance

When a batch file is being used as a persistent queue, completed IDs can be removed after a download run:

```bash
./yt-download.py --remove-completed-ids
```

The downloader compares the batch file with the configured yt-dlp download archive after a successful download run and rewrites the batch file atomically with completed IDs removed.

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
