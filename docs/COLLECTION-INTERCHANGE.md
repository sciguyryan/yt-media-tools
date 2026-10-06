# Collection interchange

The collection interchange is the versioned file format shared by Discover and Downloader when an ordered set of acquisition targets needs to retain collection context. Its first use is filtered playlists, but the format deliberately does not assume that every target is a URL, a YouTube ID, or interpreted by one particular acquisition backend.

The interchange version is independent of Discover and Downloader versions. Version 1 supports playlist-like collections.

## Purpose

Discover can turn a remote playlist into a different collection by filtering, reordering or slicing it. Passing only the resulting IDs or URLs to Downloader loses the playlist context which yt-dlp would normally provide while traversing the original playlist. Existing output templates which use fields such as `%(playlist)s` or `%(playlist_autonumber)03d` then lose information even though the user's output policy has not changed.

A collection file carries the effective ordered targets and the small amount of collection context required to restore those semantics. Downloader injects only the supported playlist context before yt-dlp performs its normal output-template processing.

The same format can describe a collection assembled by hand or by another program. A constructed collection does not need to claim that a corresponding remote playlist exists.

## Version 1 structure

A complete playlist-derived example looks like this:

```json
{
  "schema": "yt-media-tools.collection",
  "version": 1,
  "collection": {
    "type": "playlist",
    "metadata": {
      "title": "Space documentaries under 30 minutes",
      "id": "PL1234567890example",
      "uploader": "Example Astronomy",
      "uploader_id": "@exampleastronomy",
      "channel": "Example Astronomy",
      "channel_id": "UC1234567890example",
      "webpage_url": "https://www.youtube.com/playlist?list=PL1234567890example"
    }
  },
  "entries": [
    {
      "target": "a1b2c3d4e5F",
      "metadata": {
        "title": "A Tour of Mars",
        "duration": 842,
        "upload_date": "2026-02-14",
        "views": 184203
      }
    },
    {
      "target": "f6g7h8i9j0K",
      "metadata": {
        "title": "Why Saturn Has Rings",
        "duration": 1097,
        "upload_date": "2026-01-28",
        "views": 0
      }
    },
    {
      "target": "L1m2n3o4p5Q",
      "metadata": {
        "title": "The Quiet Side of the Moon",
        "duration": 1274,
        "upload_date": null,
        "views": 93511
      }
    }
  ]
}
```

This is a normal JSON document and can be copied as the starting point for a constructed collection. Only `schema`, `version`, `collection`, `entries`, each entry's non-empty `target`, and the collection type are structural requirements. `collection.metadata` may be empty when no truthful collection-level metadata exists. Per-entry `metadata` is optional so original minimal v1 documents remain valid.

`target` is deliberately opaque. It may be an ID, URL, backend-specific reference or another value accepted by the eventual acquisition path. The interchange does not reinterpret it.

The ordered `entries` array is authoritative. Positions and counts are derived from this order rather than stored separately and allowed to disagree with it. In the example above the third entry receives `playlist_index = 3`, `playlist_autonumber = 3`, `playlist_count = 3` and `n_entries = 3` when Downloader supplies playlist context to yt-dlp. Formatting such as `%(playlist_autonumber|03d)s` remains an output-template concern and is not stored in the interchange.

The machine-readable definition is `schemas/collection-interchange-v1.schema.json`.

## Projected row metadata

Discover exports the visible yt-sql projection for each result row in `entries[].metadata`. This data is distinct from the acquisition `target`.

For example:

```text
SELECT title AS name, duration FROM PLxxxxxxxxxxxxxxxxxxxxxx
```

can produce:

```json
{
  "target": "abc123",
  "metadata": {
    "name": "Example title",
    "duration": 842
  }
}
```

The query did not select `id`, so `id` is not silently added to `metadata`. Discover can still use the underlying acquisition identity as `target` while that identity remains unambiguously associated with the effective row. This separation allows the collection to preserve what the user actually selected without requiring acquisition plumbing to become part of the visible projection.

Aliases and calculated expressions retain their projected names and values. SQL `NULL` is represented as JSON `null`. Falsey values including `0`, `false` and `""` remain ordinary values. Typed date and datetime values use the same stable JSON representation as normal Discover output.

The first collection implementation discarded these projected values after identifying each target. That information-loss flaw was found during hardening and corrected before the first reconciled collection release. The distinction between `target` and `metadata` is therefore part of the settled v1 contract.

A result which has genuinely lost unambiguous acquisition identity cannot be exported merely because it contains useful values. Aggregate, grouped, synthetic or other materialised results must retain a defensible one-entry-to-one-target association or collection export fails rather than inventing a target.

Downloader validates optional entry metadata as an object but otherwise ignores it. Arbitrary projected values are not permission to patch yt-dlp's `info_dict`; only the explicit playlist metadata bridge described below can do that.

## Playlist metadata contract

Version 1 supports the following playlist-related yt-dlp fields:

| yt-dlp field | v1 source | Collection value or rule |
| --- | --- | --- |
| `playlist_title` | supplied | `collection.metadata.title` |
| `playlist_id` | supplied | `collection.metadata.id` |
| `playlist` | derived | title when present, otherwise ID |
| `playlist_uploader` | supplied | `collection.metadata.uploader` |
| `playlist_uploader_id` | supplied | `collection.metadata.uploader_id` |
| `playlist_channel` | supplied | `collection.metadata.channel` |
| `playlist_channel_id` | supplied | `collection.metadata.channel_id` |
| `playlist_webpage_url` | supplied | `collection.metadata.webpage_url` |
| `playlist_index` | derived | one-based position in the ordered collection |
| `playlist_autonumber` | derived | one-based position in the ordered collection |
| `playlist_count` | derived | number of entries in the effective collection |
| `n_entries` | derived | number of entries in the effective collection |

`playlist_index` and `playlist_autonumber` remain separate fields even though v1 gives them the same numeric sequence. They are distinct yt-dlp concepts and must not be collapsed merely because their values currently agree.

Likewise, `playlist_count` and `n_entries` remain separate integration fields even though both equal the effective entry count in v1. The original remote playlist's positions and count are not copied into a filtered collection.

General `autonumber` and `video_autonumber` fields are outside the collection metadata contract.

## Effective collection semantics

A Discover export describes the effective query result. If a source playlist contains 100 entries and the final query produces 12, the collection has 12 entries and its derived counts and positions describe those 12 entries.

Discover applies normal yt-sql filtering, ordering, `DISTINCT`, `OFFSET` and `LIMIT` semantics before collection export. The exported entry order is therefore the final query order.

For a single playlist source, stable source identity and repeated playlist metadata which agree across acquired entries may be promoted to `collection.metadata`. Conflicting repeated values are omitted rather than resolved arbitrarily. Values describing the effective result, especially positions and counts, are always derived from `entries`.

A multi-source yt-sql result is exported as a constructed collection. Its `collection.metadata` is empty rather than falsely attributing the effective collection to any one contributing remote playlist. Per-entry acquisition targets and projected metadata still follow the final query result.

Source facts are retained only while they remain truthful. A hand-built or multi-source constructed collection may use an empty metadata object rather than inventing a remote playlist ID, URL, uploader or channel.

## Discover export

Use `--collection-output FILE` to write the effective playlist result as an additional machine-readable output:

```bash
./yt-discover.py \
  --collection-output filtered-playlist.json \
  "SELECT title, duration, upload_date, view_count AS views FROM PLxxxxxxxxxxxxxxxxxxxxxx WHERE duration < 30m ORDER BY playlist_index ASC"
```

Normal Discover output is still emitted. The collection file is additional output intended for later acquisition or another consumer which needs the effective ordered result and its selected metadata.

The visible projection does not need to contain `id` merely for collection export. Discover uses retained acquisition identity where the final row still has an unambiguous underlying target. It rejects result shapes where that association no longer exists.

## Downloader consumption

Consume the exported or constructed document with:

```bash
./yt-download.py --collection-file filtered-playlist.json
```

Collection input is a first-class input source and cannot be combined with positional targets or `--input-file`. Downloader passes each `entries[].target` to yt-dlp in document order without assigning URL or ID semantics to the value.

For collection runs, Downloader loads its bundled yt-dlp pre-processing plugin. The plugin runs after extraction and before normal output-template rendering. It overlays only the supported playlist fields from this contract. Supplied collection metadata wins for those explicitly supported fields; unrelated extractor metadata remains untouched.

Collection positions and counts are injected as integers. Downloader does not perform output-template formatting itself. Padding, path separators, fallback syntax and other template behaviour remain yt-dlp responsibilities.

Each collection entry represents one acquisition target. Downloader disables remote playlist expansion for collection targets so a target which happens to identify a remote playlist cannot unexpectedly expand into several media items and break the one-entry-to-one-position contract.

## Metadata precedence

Collection metadata explicitly supplied through the supported playlist field set represents the caller's requested collection context and overrides conflicting playlist-context values returned incidentally while processing an individual target.

This precedence is deliberately narrow. `entries[].metadata` is informational projected row data and does not participate in yt-dlp metadata precedence. Undeclared or unrelated extractor metadata remains available for normal yt-dlp processing.

## Resumption, duplicates and immutability

The collection document is acquisition input, not a progress file. Re-running it preserves the same entry order and therefore the same derived positions.

Downloader's configured yt-dlp download archive remains authoritative for media already downloaded successfully. If earlier entries are skipped because they are archived, later entries keep their original collection positions rather than being renumbered according to work performed during the current run. Failed or interrupted targets remain in the immutable collection and are eligible again unless the archive proves them complete.

Duplicate targets are valid and remain distinct ordered entries. Their occurrences consume their recorded positions in order. Archive policy may skip multiple occurrences when they resolve to the same already-completed media identity, but the collection document is not rewritten.

`--remove-completed-ids` warns and has no mutation effect with `--collection-file`. `--remove-completed-rows` is rejected because row removal is a batch-queue operation rather than a collection operation. Consumers which need a different collection should produce a new collection document instead of treating this interchange as mutable progress state.

## Compatibility boundary

Version 1 accepts both the original minimal entry form:

```json
{"target": "abc123"}
```

and the corrected projected-row form:

```json
{
  "target": "abc123",
  "metadata": {
    "title": "Example title"
  }
}
```

The format remains intentionally small. It is not a generic database, a yt-dlp `info_dict` patch language or a progress ledger. Future interchange changes which require incompatible structure or semantics must use an explicit interchange-version change rather than silently changing the meaning of version 1.
