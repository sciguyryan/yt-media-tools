# yt-download

`yt-download.py` 1.14.0 is a small Python wrapper around `yt-dlp` for downloading video IDs, URLs, batch files, playlists, or newline-separated targets from standard input.

It is designed to pair naturally with `yt-discover.py`:

```bash
./yt-discover.py --tab videos \
  "FROM @channel WHERE upload_date >= TODAY()-6mo" \
| ./yt-download.py -
```

## Requirements

- Python 3.
- `yt-dlp` available on `PATH`.
- Cookies are optional. A `cookies.txt` file beside `yt-download.py` is used automatically when present.
- The script directory and configured download paths must be writable where the selected operation requires it.

The current built-in locations are:

```text
Download archive: ./archive.txt beside yt-download.py
Cookies:          ./cookies.txt beside yt-download.py, when present
Temporary files:  /mnt/storage/Temp/yt-dlp
```

Output locations are normally supplied by output profiles in the `profiles/` directory beside the script. Named download-parameter profiles live in the versioned `defaults.json` file beside the script.

## Usage

Show help:

```bash
./yt-download.py --help
```

Show the extended practical examples:

```bash
./yt-download.py --examples
```

Download one target:

```bash
./yt-download.py VIDEO_ID
```

Download several targets:

```bash
./yt-download.py VIDEO_ID_1 VIDEO_ID_2 VIDEO_ID_3
```

Read a batch file:

```bash
./yt-download.py ids.txt
```

Read targets from standard input:

```bash
printf '%s\n' VIDEO_ID_1 VIDEO_ID_2 | ./yt-download.py -
```

Select a preferred resolution:

```bash
./yt-download.py -r 1080 VIDEO_ID
```

Reverse playlist traversal:

```bash
./yt-download.py --rev PLAYLIST_URL
```

Remove exact completed IDs from a file-backed queue after successful processing, while also reconciling IDs already present in the yt-dlp archive before the run:

```bash
./yt-download.py --remove-completed-ids ids/batch.txt
```

The mode requires file-backed input. Failed, skipped, interrupted or partially processed entries remain in the file. Generated queue rewrites are atomic and preserve unrelated lines. After execution, Downloader prints a concise queue summary derived from the durable queue and archive state.

Write the same outcome information as deterministic JSON with:

```bash
./yt-download.py --remove-completed-ids --queue-report run.json ids/batch.txt
```

The report distinguishes targets requested at the start of the run, IDs already present in the configured archive, IDs whose successful completion caused them to leave the queue, and unresolved targets that remain queued. Downloader deliberately does not label an unresolved target as unavailable, skipped or failed unless that distinction can be established reliably.

Create a reusable batch file containing only unresolved targets with:

```bash
./yt-download.py --remove-completed-ids --failed-targets retry.txt ids/batch.txt
```

Both report files are replaced atomically. They are unavailable in dry-run mode because no execution outcome exists to report.

Explain the fully resolved download plan without executing yt-dlp:

```bash
./yt-download.py --explain VIDEO_ID
```

The explanation shows the selected parameter and output profiles, effective format and playlist policy, authentication source, input source, archive and temporary paths, queue behaviour, the final yt-dlp command, and where explicitly configured parameter values came from. Use `--explain-json` for a machine-readable form suitable for scripts and regression checks. Explain mode does not require yt-dlp to be installed and does not mutate queue files.

Print only the resolved `yt-dlp` command without executing it:

```bash
./yt-download.py --dry-run VIDEO_ID
```

Dry-run mode does not mutate queue files.

## Run manifests and output integrity

Write an operational JSON manifest for an actual run with:

```bash
./yt-download.py --run-manifest run.json VIDEO_ID
```

The manifest records the Downloader and detected yt-dlp versions, start and end timestamps, yt-dlp exit status, known input targets, the redacted resolved plan, queue outcome information when queue mode is active, and primary output paths reported by yt-dlp at the successful `after_move` stage. Standard-input targets are reported as unknown because Downloader does not consume or duplicate stdin merely for manifest bookkeeping.

Sensitive extractor-argument values use the same redaction contract as `--explain-json`. Cookie contents are never copied into the manifest. The internal output-event ledger is temporary and is removed after manifest construction.

Optional SHA-256 integrity values can be added with:

```bash
./yt-download.py --run-manifest run.json --hash-outputs VIDEO_ID
```

Hashes apply only to primary output files actually reported at `after_move`. They are ordinary verification aids for detecting later byte changes. They are not evidence of authenticity, provenance or who created the file. A successfully reported path that is no longer present when the manifest is built is recorded as missing rather than silently omitted.

Associated subtitle, thumbnail and info-JSON policy is recorded in the manifest, but actual sidecar paths are not guessed from output templates. Downloader will not claim a sidecar was generated unless a future implementation can observe that path authoritatively.

`--run-manifest` is intentionally unavailable with `--dry-run`, `--explain` and `--explain-json` because those modes do not perform an actual download run. `--hash-outputs` requires `--run-manifest`.

## Automated verification

Deterministic Downloader behaviour is expected to be verified by the automated test suite. Configuration precedence, command planning, queue transitions, report generation, failure handling and other reproducible behaviour should not rely on manual acceptance checks when a controlled test can exercise the same contract.

Manual verification is reserved for behaviour that genuinely depends on an external environment or service and cannot be represented faithfully with deterministic fixtures, fakes or simulated process outcomes.

## Parameter profiles

Named parameter profiles provide reusable Downloader CLI defaults without replacing explicit command-line control. The script-local `defaults.json` is used by default, or another file may be selected with `-d/--defaults`.

List available profiles:

```bash
./yt-download.py --list-parameters
```

Select one:

```bash
./yt-download.py -p 4k VIDEO_ID
```

Explicit CLI options override selected profile values:

```bash
./yt-download.py -p 4k --resolution 1080p VIDEO_ID
```

The shipped `defaults.json` contains `best`, `4k`, `1440p` and `playlist`. These profiles inherit the built-in `bv+ba/best` selector unless a profile or explicit CLI setting deliberately supplies raw `format` policy.

```json
{
  "version": 1,
  "profiles": {
    "best": {
      "resolution": "best"
    },
    "4k": {
      "resolution": "2160p"
    },
    "1440p": {
      "resolution": "1440p"
    },
    "playlist": {
      "resolution": "1080p",
      "playlist": true
    }
  }
}
```

Supported profile keys are intentionally limited to Downloader-owned configuration. Unknown keys and wrong JSON types are errors rather than being silently ignored. `format` is passed directly to yt-dlp's `-f` option.

Generate a profile from explicitly supplied eligible settings:

```bash
./yt-download.py --resolution 1440p --format 'bv+ba/best' --no-cookies --generate-profile offline-1440
```

Without `--write-profile`, the complete JSON document is written to stdout for manual inclusion. To insert the profile directly into the resolved defaults file:

```bash
./yt-download.py -d defaults.json --resolution 1440p --no-cookies \
  --generate-profile offline-1440 --write-profile
```

If the named profile already exists, the write is refused. Replacement requires explicit intent:

```bash
./yt-download.py -d defaults.json --resolution 2160p \
  --generate-profile offline-1440 --write-profile --overwrite-profile
```

When generation starts from an existing `-p` profile, that profile is copied and explicit CLI settings override it. Without a source profile, only explicitly supplied eligible settings are generated, so built-in defaults are not frozen into user profiles unnecessarily. There is deliberately no profile-removal command; `defaults.json` is human-editable.

Parameter-profile precedence is:

```text
built-in defaults -> selected parameter profile -> explicit CLI settings
```

`--auto-cookies` explicitly restores automatic script-local cookie discovery when a selected profile contains `"no-cookies": true` or a browser/file cookie source.

Operational policy can also be stored in parameter profiles. Supported settings include `limit-rate`, `throttled-rate`, `concurrent-fragments`, `retries`, `fragment-retries`, `file-access-retries`, `extractor-retries`, `retry-sleep`, `archive`, `temp-path`, `extractor-args` and `cookies-from-browser`. Declarative format settings are documented separately below. Retry counts accept non-negative integers or `"infinite"`; `retry-sleep` and `extractor-args` are ordered JSON arrays because their corresponding yt-dlp options may be repeated.

For example:

```json
{
  "version": 1,
  "profiles": {
    "patient": {
      "limit-rate": "12M",
      "concurrent-fragments": 4,
      "retries": "infinite",
      "fragment-retries": 20,
      "retry-sleep": ["linear=1:5", "fragment:exp=1:20"]
    }
  }
}
```

The same values may be supplied explicitly on the CLI. Explicit `--extractor-args` values replace Downloader's built-in extractor-argument set for that invocation, preserving the normal explicit-CLI precedence rule rather than silently combining policies.

## Operational policy

The most common network and retry controls have first-class Downloader options:

```bash
./yt-download.py --limit-rate 12M -N 4 --retries infinite VIDEO_ID
./yt-download.py --fragment-retries 20 --retry-sleep fragment:exp=1:20 VIDEO_ID
./yt-download.py --archive ~/media/archive.txt --temp-path ~/media/tmp VIDEO_ID
```

Downloader keeps its existing `20M` rate limit, script-local archive, temporary path and extractor arguments as built-in defaults. Retry counts, throttled-rate detection and concurrent fragment downloads are left at yt-dlp's defaults unless a parameter profile or explicit CLI setting chooses them.

`--explain` and `--explain-json` include these resolved operational values and their configured archive/temporary paths. Sensitive extractor-argument values such as tokens, keys and credentials are redacted from explanation output. `--dry-run` remains an exact command preview and therefore may contain explicitly configured sensitive values; treat its output accordingly.

## Declarative format policy

Downloader can express common format requirements without requiring a raw yt-dlp selector. Hard requirements and preferences are deliberately different. Hard requirements remove unacceptable candidates; preferences alter ordering but allow yt-dlp to fall back when the preferred representation is unavailable.

Resolution and frame-rate bounds are hard requirements:

```bash
./yt-download.py --min-resolution 1080 --max-resolution 2160 VIDEO_ID
./yt-download.py --min-fps 30 --max-fps 60 VIDEO_ID
```

Codec, frame-rate, HDR and audio-channel preferences are fallback-friendly:

```bash
./yt-download.py --preferred-video-codec av01 --preferred-audio-codec opus VIDEO_ID
./yt-download.py --preferred-fps 60 --preferred-hdr hdr --preferred-audio-channels 6 VIDEO_ID
```

`--preferred-hdr` accepts `sdr`, `hdr` and `dv`. `hdr` follows yt-dlp's compatibility-oriented HDR sorting through `hdr:12`; `dv` allows Dolby Vision to rank highest, while `sdr` reverses HDR preference. These are preferences rather than requirements.

When separate streams must be merged, `--merge-container` may choose one of yt-dlp's supported merge containers:

```bash
./yt-download.py --merge-container mkv VIDEO_ID
```

This controls the container used for a merge only. It does not force remuxing or transcoding when no merge is required. Those operations remain separate future policy decisions.

The corresponding parameter-profile keys are `min-resolution`, `max-resolution`, `min-fps`, `max-fps`, `preferred-fps`, `preferred-video-codec`, `preferred-audio-codec`, `preferred-hdr`, `preferred-audio-channels` and `merge-container`.

Raw `-f/--format` remains the expert selector authority. Downloader rejects a raw selector combined with hard min/max resolution or FPS constraints instead of silently editing the raw expression. Sorting preferences and merge-container policy may still accompany a raw selector because they do not rewrite it.

Use `--explain` or `--explain-json` to inspect the exact generated selector and sort order before downloading.

## First-class audio workflows

Audio-only source selection and audio conversion are separate policies. `--audio-only` selects an already available audio stream and does not enable FFmpeg conversion:

```bash
./yt-download.py --audio-only VIDEO_ID
./yt-download.py --audio-only --preferred-audio-codec opus VIDEO_ID
```

Exact source codec and container requirements may be stated independently of conversion:

```bash
./yt-download.py --audio-only --audio-source-codec opus --audio-source-container webm VIDEO_ID
./yt-download.py --audio-only --audio-source-codec opus --no-audio-source-fallback VIDEO_ID
```

When an exact source requirement is given, Downloader falls back to another existing audio stream by default. `--no-audio-source-fallback` makes the source codec/container requirement strict. This fallback remains source selection: it does not transcode.

Conversion is an explicit opt-in through `--audio-format`. Supplying it enables yt-dlp's audio extraction post-processor and therefore permits FFmpeg conversion:

```bash
./yt-download.py --audio-format flac VIDEO_ID
./yt-download.py --audio-format mp3 --audio-quality 192K VIDEO_ID
```

Supported conversion formats are `best`, `aac`, `alac`, `flac`, `m4a`, `mp3`, `opus`, `vorbis` and `wav`, following the current yt-dlp audio extraction surface. `--audio-quality` accepts VBR values from `0` (best) through `10` (worst), or an explicit bitrate such as `128K`, and is invalid unless conversion is enabled.

Audio workflows reject video-only resolution, frame-rate, video-codec, HDR and merge-container policy rather than silently ignoring it. Raw `-f/--format` is also mutually exclusive with first-class audio mode, keeping expert raw selection and typed audio policy as separate authorities. Subtitle sidecars remain available, but subtitle embedding is rejected for an audio-only primary output.

The corresponding parameter-profile keys are `audio-only`, `audio-source-codec`, `audio-source-container`, `audio-source-fallback`, `audio-format` and `audio-quality`. Existing `preferred-audio-codec` and `preferred-audio-channels` remain fallback-friendly source sorting preferences in audio mode.

Use `--explain` or `--explain-json` to see whether the resolved run is source-only or conversion-enabled before execution.

## Associated artefacts and metadata

Downloader treats the downloaded media as the primary requested output. Subtitle files, thumbnails and info JSON are optional associated artefacts unless explicitly requested. The historical embedded metadata, embedded chapter and SponsorBlock-removal defaults are preserved, but they are now visible typed policy rather than hard-coded command fragments.

Manual and automatic subtitles can be selected independently. Language and format selectors are passed through to yt-dlp's dedicated subtitle options:

```bash
./yt-download.py --write-subs --sub-langs 'en.*,cy' --sub-format 'srt/best' VIDEO_ID
./yt-download.py --write-auto-subs --sub-langs 'en.*' VIDEO_ID
```

Embedding is a separate choice, so a sidecar can be retained while subtitles are also embedded when the output container supports it:

```bash
./yt-download.py --write-subs --sub-langs en --embed-subs VIDEO_ID
```

Thumbnail and information-JSON sidecars are opt-in:

```bash
./yt-download.py --write-thumbnail --write-info-json VIDEO_ID
```

Thumbnail embedding is also independent:

```bash
./yt-download.py --embed-thumbnail VIDEO_ID
```

Metadata and chapters remain embedded by default for compatibility with earlier Downloader releases. Either can be disabled explicitly or from a parameter profile:

```bash
./yt-download.py --no-embed-metadata --no-embed-chapters VIDEO_ID
```

SponsorBlock processing remains enabled by default with removal category `all`, preserving the established Downloader command. Marking and removal categories can be selected independently:

```bash
./yt-download.py --sponsorblock-mark sponsor,intro --sponsorblock-remove selfpromo VIDEO_ID
```

`--no-sponsorblock` disables both marking and removal. Category expressions are validated against the categories supported by yt-dlp; `poi_highlight` and `chapter` are accepted for marking but rejected for removal because yt-dlp does not permit them there.

The corresponding parameter-profile keys are `write-subs`, `write-auto-subs`, `sub-langs`, `sub-format`, `embed-subs`, `write-thumbnail`, `embed-thumbnail`, `write-info-json`, `embed-metadata`, `embed-chapters`, `sponsorblock`, `sponsorblock-mark` and `sponsorblock-remove`. Boolean settings have matching positive and negative CLI forms so explicit CLI choices can override a selected profile in either direction.

`--explain` and `--explain-json` report all of these resolved choices. Run manifests reuse that resolved policy and distinguish the primary media output from explicitly requested associated artefacts without inferring policy from the final command.

## Cookies

Cookies are optional. If `cookies.txt` exists beside `yt-download.py`, it is used automatically. If the file is absent, yt-dlp runs without cookies.

Use an explicit cookie file with:

```bash
./yt-download.py --cookies /path/to/cookies.txt VIDEO_ID
```

Cookies may also be loaded directly from a browser using yt-dlp's browser specification:

```bash
./yt-download.py --cookies-from-browser firefox VIDEO_ID
./yt-download.py --cookies-from-browser chromium+kwallet6:Default VIDEO_ID
```

Cookie-file selection, browser cookies and `--no-cookies` are mutually exclusive. An explicitly requested cookie file must exist. To disable cookies even when the script-local file exists, use:

```bash
./yt-download.py --no-cookies VIDEO_ID
```

## Output profiles

Output profiles are separate from parameter profiles. They control path and filename layout only. `-P/--output-profile` selects them; the legacy long option `--profile` remains available as an alias.

Profiles are UTF-8 text files stored under `profiles/` beside the downloader. A profile begins with `@profile` and may define `path`, `output`, or both.

Example:

```text
@profile

path=/mnt/storage/Downloads/YouTube/
output=%(title)s [%(id)s] [%(uploader)s].%(ext)s
```

Select a profile by name:

```bash
./yt-download.py -P playlist PLAYLIST_URL
```

Bare profile names are resolved beneath `profiles/`. An explicit path may also be supplied.

Profile fallback is:

```text
requested profile -> profiles/default -> yt-dlp native output defaults
```

A missing profile is recoverable. An existing but invalid profile is a configuration error.

The bundle includes `profiles/default` and `profiles/playlist`.

## Relationship to yt-discover

`yt-discover.py` is responsible for discovery, metadata acquisition and yt-sql querying. `yt-download.py` is responsible for downloading the resulting IDs or URLs. Keeping discovery output on stdout and diagnostics on stderr allows the tools to compose safely in shell pipelines.
