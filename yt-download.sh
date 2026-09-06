#!/usr/bin/env bash

# Wrapper around my usual yt-dlp command.
# This has grown enough options that it is probably becoming a problem of its own.

RESOLUTION=1440
BATCH_FILE=""
PLAYLIST_REVERSE=""
OUTPUT_DIR="/mnt/storage/Downloads/YouTube"
COOKIES_FILE="cookies.txt"
ARCHIVE_FILE="archive.txt"
RATE_LIMIT="20M"
TARGETS=()

usage() {
    echo "Usage: $0 [options] [URL|ID ...]"
    echo
    echo "Options:"
    echo "  -b, --batch-file FILE       Read URLs/IDs from FILE"
    echo "  -r, --resolution HEIGHT     Prefer this vertical resolution (default: 1440)"
    echo "  -o, --output-dir DIR        Download into DIR"
    echo "      --cookies FILE          Read cookies from FILE"
    echo "      --archive FILE          Use FILE as the download archive"
    echo "      --rate-limit RATE       Limit download rate (default: 20M)"
    echo "      --playlist-reverse      Traverse playlists in reverse order"
    echo "  -h, --help                  Show this help"
    echo
    echo "If no URL, ID or batch file is supplied, ids.txt is used."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -b|--batch-file)
            BATCH_FILE="$2"
            shift 2
            ;;
        -r|--resolution)
            RESOLUTION="$2"
            shift 2
            ;;
        -o|--output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --cookies)
            COOKIES_FILE="$2"
            shift 2
            ;;
        --archive)
            ARCHIVE_FILE="$2"
            shift 2
            ;;
        --rate-limit)
            RATE_LIMIT="$2"
            shift 2
            ;;
        --playlist-reverse)
            PLAYLIST_REVERSE="--playlist-reverse"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            TARGETS+=("$1")
            shift
            ;;
    esac
done

if [ -z "$BATCH_FILE" ] && [ "${#TARGETS[@]}" -eq 0 ]; then
    BATCH_FILE="ids.txt"
fi

ARGS=(
    -f "bv+ba/best"
    -S "res:${RESOLUTION},lang,fps,size"
    -r "$RATE_LIMIT"
    --mtime
    --embed-metadata
    --embed-thumbnail
    --embed-subs
    --sub-langs "en.*"
    --download-archive "$ARCHIVE_FILE"
    --cookies "$COOKIES_FILE"
    --windows-filenames
    -o "${OUTPUT_DIR}/%(title)s [%(id)s] [%(uploader)s].%(ext)s"
)

if [ -n "$PLAYLIST_REVERSE" ]; then
    ARGS+=("$PLAYLIST_REVERSE")
fi

if [ -n "$BATCH_FILE" ]; then
    ARGS+=(--batch-file "$BATCH_FILE")
else
    ARGS+=("${TARGETS[@]}")
fi

yt-dlp "${ARGS[@]}"
