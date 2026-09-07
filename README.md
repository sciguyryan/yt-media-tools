# YouTube downloader

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

## Other options

Run the built-in help for the complete option list:

```bash
./yt-download.py --help
```
