# Collection interchange

This document starts the collection-interchange work tracked by #136 and #137. It is deliberately a working design note at this stage. The contract should become more formal as Discover export and Downloader consumption make the edge cases concrete.

## Why this exists

Discover can turn a remote collection into a different effective collection. A playlist might contain hundreds of entries, while a query keeps only a selected subset or puts them in a different order. Passing the resulting targets to Downloader works, but the collection context has been lost by then. yt-dlp sees independent targets rather than entries reached through playlist traversal, so playlist-aware output templates no longer receive the metadata they expected.

The interchange should carry that missing context without teaching Discover or Downloader how to render filenames. Downloader can map the effective collection metadata into yt-dlp's normal metadata processing, leaving yt-dlp to apply the selected output template.

The same format should also describe a collection which never existed remotely. A user or another program should be able to provide an ordered group of targets and collection metadata, then have Downloader treat that group consistently with a Discover-produced collection.

## Generic shape

The generic envelope is a collection, an ordered set of entries, and enough schema information to validate what the producer meant. It must not assume that a target is a URL, a YouTube ID, or anything else understood by one particular backend.

A deliberately incomplete sketch is:

```json
{
  "schema": "...",
  "collection": {
    "...": "..."
  },
  "entries": [
    {"target": "..."},
    {"target": "..."}
  ]
}
```

`target` means an acquisition input. Its final representation is not fixed by this sketch. If the first implementation needs target typing or a source namespace to make interpretation unambiguous, that belongs in the contract rather than being inferred from a field called `url` or `id`.

The file is an input manifest, not mutable download progress. Re-running a collection should not rewrite its ordering merely because some entries are already in the download archive.

## yt-dlp playlist metadata audit

Current yt-dlp documents the following playlist-related output-template fields. They do not all mean the same kind of thing, so the interchange should not simply serialise them as one flat dictionary.

| yt-dlp field | Meaning in yt-dlp | Interchange treatment |
| --- | --- | --- |
| `playlist_id` | Identifier of the containing playlist | Source/effective collection identity where meaningful; optional for constructed collections |
| `playlist_title` | Name of the containing playlist | Collection metadata; may be supplied for constructed collections |
| `playlist` | Playlist title when available, otherwise playlist ID | Derived during Downloader mapping rather than stored as an independent authority |
| `playlist_uploader` | Full name of playlist uploader | Optional source collection metadata |
| `playlist_uploader_id` | Nickname or identifier of playlist uploader | Optional source collection metadata |
| `playlist_channel` | Display name of channel which uploaded playlist | Optional source collection metadata |
| `playlist_channel_id` | Identifier of channel which uploaded playlist | Optional source collection metadata |
| `playlist_webpage_url` | Playlist webpage URL | Optional source provenance; must not be invented for constructed collections |
| `playlist_count` | Total items in the playlist; may be unknown without full extraction | Source collection fact when known; not automatically the size of a filtered result |
| `playlist_index` | Entry index in playlist, with behaviour affected by playlist selection/reversal | Source/traversal position when genuinely known; do not silently redefine it as filtered-result position |
| `n_entries` | Total extracted items in the playlist/download queue | Derived from the effective interchange entry set supplied to Downloader |
| `playlist_autonumber` | Position in the playlist download queue | Derived from stable interchange entry order |

The important split is between **source collection facts** and **effective collection facts**. A filtered result can still remember that an entry came from position 27 of a source playlist while being entry 3 in the effective collection passed to Downloader. Treating both as one index would lose information.

`playlist_index` therefore remains source/traversal metadata when it is available. `playlist_autonumber` is generated from the effective ordered entry set. `n_entries` is likewise an effective count. This preserves the useful yt-dlp distinction instead of manufacturing a new source position after filtering.

`playlist_count` needs the same care. yt-dlp describes it as the size of the playlist and notes that it may be unknown when the complete playlist has not been extracted. It should not be rewritten to the filtered result count merely because Discover returned fewer entries. The effective count belongs in `n_entries` when Downloader maps the interchange into yt-dlp metadata.

## Collection metadata and provenance

A collection may be derived from a real source, wholly constructed, or eventually produced by something other than Discover. The generic format should therefore keep effective collection metadata separate from source provenance where preserving that distinction matters.

A Discover export should describe the ordered result it actually produced. Values derived from that result, such as effective entry count and automatic numbering, must reflect filtering and ordering. Genuine source facts may be retained when they remain true, but they must not be made to look like properties of a newly constructed collection when they are only provenance.

Constructed collections need no fictional remote identity. A title can be enough for a playlist-style output template. Remote playlist IDs, uploader identities and webpage locations are optional facts, not fields which must be fabricated to make the format valid.

## Mapping into yt-dlp

Downloader should perform the translation from the generic collection contract into yt-dlp's playlist metadata vocabulary. The interchange itself should not depend on yt-dlp field names except where a provider-specific extension is deliberately defined later.

For an ordered effective collection, the expected mapping is broadly:

- collection title/identity and genuine source metadata provide the corresponding playlist context where declared;
- `playlist` is derived using yt-dlp-compatible title/identifier semantics rather than stored independently;
- `n_entries` is the effective number of entries supplied by the interchange;
- `playlist_autonumber` is the one-based position of each entry in that stable effective order;
- `playlist_index` is supplied only when the entry carries a genuine source/traversal position with the intended semantics;
- formatting and padding remain entirely in yt-dlp's output-template machinery.

An existing template such as `%(playlist_autonumber|03d)s` must therefore continue to own presentation. The interchange supplies the integer position, not the rendered `001` string or a replacement format specification.

## Precedence

The first implementation needs an explicit precedence rule rather than relying on incidental extractor behaviour. An interchange field which is deliberately declared as effective collection metadata should be authoritative for the corresponding collection context. Undeclared fields remain available for normal backend/extractor metadata where that is meaningful.

This does not create a general metadata-overwrite facility. The supported collection fields are a small typed contract, and Downloader maps only those fields whose semantics have been defined.

## Resumption and the download archive

The collection retains its complete stable ordering between runs. The initial design expects yt-dlp's existing download archive to remain authoritative for successful acquisitions: already archived entries can be encountered and skipped while unresolved entries remain eligible.

Skipping an archived entry must not renumber later entries. If entry 17 in the interchange is the first item which still needs downloading, its effective automatic number remains 17.

`--remove-completed-ids` is not a collection-progress mechanism. When Downloader consumes a collection file, that option must not be presented as removing completed entries from the collection file. The implementation should warn clearly about that interaction while leaving the collection intact.

Before relying on archive traversal for large collections, the Downloader work should verify where yt-dlp performs archive rejection and whether replaying many completed entries has a material cost. Separate persistent collection-progress state should only be introduced if the existing archive behaviour proves insufficient.

## First-version boundaries

The first version should support the playlist-like metadata needed to preserve existing playlist-aware output profiles and constructed ordered collections. It should remain deliberately smaller than a generic metadata transport.

The contract must be versioned and language-neutral. Discover and Downloader remain independent programs: Discover may produce the file, Downloader may consume it, and neither should require importing the other's implementation. A hand-written or third-party producer should be able to create the same format once the schema is formalised.

Still to settle during implementation:

- the exact schema identifier and versioning representation;
- the target representation and whether target typing is required;
- the precise collection/provenance object shape;
- which source playlist fields Discover can obtain reliably from each supported backend;
- how duplicate targets are identified without assuming target strings are globally unique identities;
- validation and forward-compatibility rules;
- the exact yt-dlp injection point and archive-skip cost.
