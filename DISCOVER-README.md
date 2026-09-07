# YouTube discovery

`yt-discover.py` is a small companion to the downloader for finding video IDs from a YouTube channel or playlist.

It uses `yt-dlp` to enumerate the source and prints matching video IDs, one per line. The output can be redirected to a file or piped into the downloader.

## Basic use

Print all IDs found in a source:

```bash
./yt-discover.py CHANNEL_OR_PLAYLIST_URL
```

Filter by upload date:

```bash
./yt-discover.py CHANNEL_URL --after 2024-01-01
./yt-discover.py CHANNEL_URL --before 2024-12-31
./yt-discover.py CHANNEL_URL --after 2024-01-01 --before 2024-12-31
```

Filter titles using a case-insensitive substring:

```bash
./yt-discover.py CHANNEL_URL --title interview
```

Print matching entries in reverse source order:

```bash
./yt-discover.py CHANNEL_URL --reverse
```

The current discovery script relies on the metadata available from `yt-dlp --flat-playlist`. Entries without an upload date cannot match date filters.

## Downloader integration

Save discovered IDs for later:

```bash
./yt-discover.py CHANNEL_URL --title interview > ids.txt
./yt-download.py
```

Or pass them through standard input:

```bash
./yt-discover.py CHANNEL_URL --title interview | ./yt-download.py -
```
