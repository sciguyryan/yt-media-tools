#!/usr/bin/env bash

# Download the IDs in ids.txt automatically, using my usual yt-dlp settings.
yt-dlp \
    -f "bv+ba/best" \
    -S "res:1440,lang,fps,size" \
    -r 20M \
    --mtime \
    --embed-metadata \
    --download-archive archive.txt \
    --cookies cookies.txt \
    -o "/mnt/storage/Downloads/YouTube/%(title)s [%(id)s] [%(uploader)s].%(ext)s" \
    --batch-file ids.txt
