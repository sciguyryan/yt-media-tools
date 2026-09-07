# YouTube Media Tools

This repository contains two related command-line tools:

- `yt-discover.py` discovers and queries YouTube items using filters or YT-SQL.
- `yt-download.py` downloads direct targets or persistent file-backed queues through yt-dlp.

Shared Discover implementation lives in `yt_media_tools/`. Downloader profiles live in `profiles/`.

## Requirements

- Python 3.11 or later
- yt-dlp
- Node.js when the YouTube.js backend is used
- Ruff for repository linting and formatting checks
- pytest for the automated test suite

## Discover

Run `python yt-discover.py --help` for the complete command-line interface. See `DISCOVER-README.md` for Discover usage and `YT-SQL.md` for the query language.

## Downloader

Run `python yt-download.py --help` for the complete interface and `python yt-download.py --examples` for practical examples. See `DOWNLOADER-README.md` for Downloader usage.

Profiles control only output location and output template. With `--remove-completed-ids`, file-backed queues are reconciled against the archive before execution and updated per completed download through yt-dlp's `after_move` hook.

## Profiles

Profiles use the `@profile` format and support only `path` and `output`.

```text
@profile

path=/mnt/storage/Downloads/YouTube/
output=%(title)s [%(id)s] [%(uploader)s].%(ext)s
```

## Development

```bash
python -m pytest -q
python -m pytest -m stress
ruff check .
ruff format --check .
```

GitHub Actions runs Ruff in check-only mode. Release history and repository-level changes are recorded in `CHANGELOG.md`.
