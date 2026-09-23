# NewPipeExtractor benchmark bridge

This small JVM application exists only for the experimental metadata-provider benchmark used by yt-discover issue #109. It is not a production acquisition backend.

It pins NewPipeExtractor v0.26.5 and exposes one JSON-lines operation for known YouTube video IDs. The bridge keeps one JVM alive for the complete input corpus so the benchmark can distinguish JVM/process startup cost from per-item extraction cost.

Build the installed application with:

```bash
cd tools/newpipe-extractor-bridge
gradle installDist
```

The metadata benchmark discovers the resulting launcher under `build/install/yt-media-tools-newpipe-bridge/bin/yt-media-tools-newpipe-bridge`. Alternatively, set `YT_DISCOVER_NEWPIPE_BRIDGE` to an explicit launcher path.

The bridge uses Java's HTTP client as the NewPipeExtractor `Downloader` implementation. It is intentionally minimal and should not be treated as a general NewPipe client.
