#!/usr/bin/env bash

# A slightly less painful wrapper around my usual yt-dlp command.
# With no arguments it still downloads everything listed in ids.txt.

RESOLUTION=1440
BATCH_FILE=""
PLAYLIST_REVERSE=""
TARGETS=()

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
        --playlist-reverse)
            PLAYLIST_REVERSE="--playlist-reverse"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [-b FILE] [-r HEIGHT] [--playlist-reverse] [URL|ID ...]"
            echo "If no URL, ID or batch file is supplied, ids.txt is used."
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
    -r 20M
    --mtime
    --embed-metadata
    --download-archive archive.txt
    --cookies cookies.txt
    -o "/mnt/storage/Downloads/YouTube/%(title)s [%(id)s] [%(uploader)s].%(ext)s"
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
