# Collection interchange

This document describes the collection file shared by Discover and Downloader. It starts deliberately small. The immediate problem is playlist metadata, but the outer format should not assume that every target is a URL, a YouTube ID, or even something interpreted by the same acquisition backend.

The format is versioned separately from Discover and Downloader. Version 1 supports playlist-like collections.

## Why this exists

Discover can turn a remote playlist into a different useful collection. A query might remove unwanted entries, change their order, or select only a small part of the original. Passing the resulting targets to Downloader as ordinary line-based input loses the playlist context which yt-dlp would normally provide while traversing the original playlist.

That matters when an existing Downloader profile contains fields such as `%(playlist)s` or `%(playlist_autonumber|03d)s`. The profile is not the problem. The metadata has disappeared before yt-dlp gets to render it.

The collection file carries that missing context alongside the ordered targets. Downloader can later turn the supported collection metadata into yt-dlp metadata and leave yt-dlp to perform its normal output-template work.

The same format should also work for a collection assembled by hand or by another program. There does not need to be a real remote playlist behind it.

## Version 1 shape

A minimal file looks like this:

```json
{
  "schema": "yt-media-tools.collection",
  "version": 1,
  "collection": {
    "type": "playlist",
    "metadata": {
      "title": "Things I actually wanted"
    }
  },
  "entries": [
    {"target": "first-target"},
    {"target": "second-target"},
    {"target": "third-target"}
  ]
}
```

`target` is deliberately opaque. It might contain a URL, an ID, a backend-specific reference, or another target representation accepted by the eventual acquisition path. The collection format does not reinterpret it.

The ordered `entries` array is authoritative for the effective collection. Derived positions and counts come from that order rather than being stored separately and allowed to disagree with it.

The machine-readable v1 shape lives in `schemas/collection-interchange-v1.schema.json`.

## Playlist metadata audit

The initial audit follows the playlist-related fields which yt-dlp exposes to output templates. They do not all mean the same sort of thing.

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
| `playlist_index` | derived | one-based position in the effective ordered collection |
| `playlist_autonumber` | derived | one-based position in the effective download queue |
| `playlist_count` | derived | number of entries in the effective collection |
| `n_entries` | derived | number of entries supplied by the effective collection |

`playlist_index` and `playlist_autonumber` are kept as separate yt-dlp fields even though a simple v1 collection initially gives them the same numeric sequence. yt-dlp gives them different meanings, and later Downloader policy must not collapse the two concepts merely because their values happen to agree in the first implementation.

Likewise, `playlist_count` and `n_entries` remain separate integration fields. For a complete v1 collection they are both derived from the effective entry count. This avoids carrying the original remote playlist's count into a filtered collection and then claiming it describes the new one.

The general `autonumber` and `video_autonumber` fields are not collection metadata and are outside this contract.

## Effective collection, not copied playlist state

A Discover export describes its result. If a source playlist contains 100 entries and a query produces 12, the exported collection has 12 entries. Its derived count and position fields must describe those 12 entries.

Source facts may be copied into `metadata` only while they still mean what they say. A title, uploader or channel can remain useful after filtering. A remote playlist ID or webpage URL needs more care because a constructed collection is not necessarily the remote resource identified by those values. Discover export work must make that distinction deliberately rather than copying every source field by default.

A hand-built collection can omit metadata which has no honest value. Downloader should not need a fake remote ID or URL merely to supply a title and stable numbering.

## Metadata precedence

Version 1 treats metadata explicitly present in the collection as the collection context requested by the caller. When Downloader consumes the format, supported supplied fields are intended to override conflicting playlist-context values returned incidentally while processing an individual target. Metadata not declared by the collection remains available for normal yt-dlp processing.

This precedence applies only to the small supported playlist field set. The format is not an arbitrary yt-dlp info-dict patch mechanism.

## Downloader consumption

Downloader accepts a version 1 collection with `--collection-file FILE`. The collection is the input source for that invocation, so it cannot be combined with positional targets or `--input-file`. Each `entries[].target` value is passed to yt-dlp in document order without the interchange assigning URL or ID semantics to it.

Downloader loads a small bundled yt-dlp pre-processing plugin for collection runs. The plugin runs after extraction and before yt-dlp performs its normal output-template work. It overlays only the supported playlist fields declared by this contract. Supplied collection metadata wins for the fields which are present, while unrelated extractor metadata is left alone. Positions and counts are injected as integers derived from the ordered `entries` array.

For a three-entry collection, the second effective entry therefore receives `playlist_index = 2`, `playlist_autonumber = 2`, `playlist_count = 3` and `n_entries = 3`. `playlist` is derived from the supplied title when one exists, otherwise from the supplied collection ID. Downloader does not render `03d`, choose path separators or otherwise reproduce output-template formatting. Those remain normal yt-dlp responsibilities.

Collection entries are treated as individual members of the effective collection. Downloader disables remote playlist expansion for these targets so an entry which happens to identify a remote playlist cannot unexpectedly expand into several media items and invalidate the one-entry/one-position relationship.

The bridge is deliberately not a general yt-dlp metadata patch surface. Version 1 injects only the playlist fields listed in this document.

## Resumption and mutation

The collection document is acquisition input, not a progress file. Re-running it should preserve the same entry order and therefore the same derived positions. Downloader's existing download archive is expected to remain the authority for media already downloaded successfully; the later Downloader work must verify that this gives correct and reasonably efficient resumption.

Queue-mutation features such as `--remove-completed-ids` must not rewrite a collection document. Downloader should warn when that option is combined with collection input so it is clear that completed collection entries will not be removed from the file.

## Discover export

Discover can write the effective result of a single playlist query with `--collection-output FILE`. The ordinary query output is unchanged; the collection file is an additional machine-readable result.

The `entries` array follows the final query result order after the query has applied its filtering, ordering, DISTINCT, OFFSET and LIMIT semantics. Original playlist positions and counts are not copied into the document. Downloader can therefore derive positions and counts from the collection that was actually selected rather than from the remote playlist before Discover changed it.

Version 1 collection export requires every final query row to expose a non-empty `id` field. This is deliberate. An aggregate or projection such as `SELECT uploader` does not identify an ordered set of acquisition targets, and Discover must not guess which underlying media the result represents. A query intended for collection export should retain `id` in its effective rows.

For the first implementation, Discover exports one playlist source at a time. Stable source identity and repeated playlist metadata which agree across acquired entries may be retained as collection metadata. Conflicting repeated values are omitted rather than choosing one arbitrarily. Values which describe the effective result, including counts and positions, remain derived from `entries`.

The fully developed version of this document should include a complete realistic playlist collection which can be copied and adapted directly. The example will be expanded as Downloader consumption and constructed-collection behaviour make the remaining semantics concrete.

## Work still deliberately left for later issues

This issue defines the first contract, not the whole feature. Discover export still needs to decide which source metadata remains truthful after each query result is formed. Downloader now validates and consumes the document and injects the supported playlist values before normal yt-dlp template processing. Archive-backed resumption still needs deliberate verification. Constructed collections and awkward cases then need hardening against the same contract.

The document should become more formal as those implementations establish stronger invariants. For now it records the boundary we intend the next pieces to implement without pretending that unimplemented behaviour has already become permanent.
