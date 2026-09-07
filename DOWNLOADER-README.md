# yt-download

`yt-download.py` 1.6.0 is a small Python wrapper around `yt-dlp` for downloading video IDs, URLs, batch files, playlists, or newline-separated targets from standard input.

It is designed to pair naturally with `yt-discover.py`:

```bash
./yt-discover.py --tab videos \
  "FROM @channel WHERE upload_date >= TODAY()-6mo" \
| ./yt-download.py -
```

## Requirements

- Python 3.
- `yt-dlp` available on `PATH`.
- Cookies are optional. A `cookies.txt` file beside `yt-download.py` is used automatically when present.
- The script directory and configured download paths must be writable where the selected operation requires it.

The current built-in locations are:

```text
Download archive: ./archive.txt beside yt-download.py
Cookies:          ./cookies.txt beside yt-download.py, when present
Temporary files:  /mnt/storage/Temp/yt-dlp
```

Output locations are normally supplied by profiles in the `profiles/` directory beside the script.

## Usage

Show help:

```bash
./yt-download.py --help
```

Show the extended practical examples:

```bash
./yt-download.py --examples
```

Download one target:

```bash
./yt-download.py VIDEO_ID
```

Download several targets:

```bash
./yt-download.py VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3
```

Read a batch file:

```bash
./yt-download.py ids.txt
```

Read targets from standard input:

```bash
printf '%s\n' VIDEO_ID_1 VIDEO_ID_2 | ./yt-download.py -
```

Select a preferred resolution:

```bash
./yt-download.py -r 1080 VIDEO_ID
```

Reverse playlist traversal:

```bash
./yt-download.py --rev PLAYLIST_URL
```

Remove exact completed IDs from a file-backed queue after successful processing, while also reconciling IDs already present in the yt-dlp archive before the run:

```bash
./yt-download.py --remove-completed-ids ids/batch.txt
```

The mode requires file-backed input. Failed, skipped, interrupted or partially processed entries remain in the file. Generated queue rewrites are atomic and preserve unrelated lines.

Print the resolved `yt-dlp` command without executing it:

```bash
./yt-download.py --dry-run VIDEO_ID
```

Dry-run mode does not mutate queue files.

## Cookies

Cookies are optional. If `cookies.txt` exists beside `yt-download.py`, it is used automatically. If the file is absent, yt-dlp runs without cookies.

Use an explicit cookie file with:

```bash
./yt-download.py --cookies /path/to/cookies.txt VIDEO_ID
```

An explicitly requested cookie file must exist. To disable cookies even when the script-local file exists, use:

```bash
./yt-download.py --no-cookies VIDEO_ID
```

## Output profiles

Profiles are UTF-8 text files stored under `profiles/` beside the downloader. A profile begins with `@profile` and may define `path`, `output`, or both.

Example:

```text
@profile

path=/mnt/storage/Downloads/YouTube/
output=%(title)s [%(id)s] [%(uploader)s].%(ext)s
```

Select a profile by name:

```bash
./yt-download.py --profile playlist PLAYLIST_URL
```

Bare profile names are resolved beneath `profiles/`. An explicit path may also be supplied.

Profile fallback is:

```text
requested profile -> profiles/default -> yt-dlp native output defaults
```

A missing profile is recoverable. An existing but invalid profile is a configuration error.

The bundle includes `profiles/default` and `profiles/playlist`.

## Relationship to yt-discover

`yt-discover.py` is responsible for discovery, metadata acquisition and yt-sql querying. `yt-download.py` is responsible for downloading the resulting IDs or URLs. Keeping discovery output on stdout and diagnostics on stderr allows the tools to compose safely in shell pipelines.
