# Python Downloader argument inventory

This inventory is extracted from the `add_argument` calls in the packaged `yt-download.py` source using Python AST parsing. It is an accounting aid, not proof of CLI parity. Flags in the same row are aliases of one parser definition. The source line is provided for review.

| Python source line | Argument spellings | Part 3 accounting |
| ---: | --- | --- |
| 782 | `targets` | Positional target; execution deferred |
| 788 | `-p`, `--profile`, `--parameter-profile` | Rust subset implemented; parity review required |
| 796 | `-d`, `--defaults` | Rust subset implemented; parity review required |
| 803 | `--list-profiles`, `--list-parameters` | Rust subset implemented; parity review required |
| 810 | `--profile-tree` | Rust subset implemented; parity review required |
| 817 | `--schema-json` | Rust subset implemented; parity review required |
| 822 | `--validate-config` | Rust subset implemented; parity review required |
| 829 | `--capabilities` | Argument exclusivity in Part 3; report content deferred to Parts 4-5 |
| 834 | `--capabilities-json` | Argument exclusivity in Part 3; report content deferred to Parts 4-5 |
| 839 | `-r`, `--resolution` | Not yet mapped; classify before Part 3 closure |
| 849 | `-f`, `--format` | Not yet mapped; classify before Part 3 closure |
| 860 | `--min-resolution` | Not yet mapped; classify before Part 3 closure |
| 865 | `--max-resolution` | Not yet mapped; classify before Part 3 closure |
| 870 | `--min-fps` | Not yet mapped; classify before Part 3 closure |
| 871 | `--max-fps` | Not yet mapped; classify before Part 3 closure |
| 872 | `--preferred-fps` | Not yet mapped; classify before Part 3 closure |
| 875 | `--preferred-video-codec` | Not yet mapped; classify before Part 3 closure |
| 880 | `--preferred-audio-codec` | Not yet mapped; classify before Part 3 closure |
| 885 | `--preferred-hdr` | Not yet mapped; classify before Part 3 closure |
| 890 | `--preferred-audio-channels` | Not yet mapped; classify before Part 3 closure |
| 896 | `--merge-container` | Not yet mapped; classify before Part 3 closure |
| 905 | `--audio-only` | Rust subset implemented; parity review required |
| 912 | `--no-audio-only` | Rust subset implemented; parity review required |
| 918 | `--audio-source-codec` | Not yet mapped; classify before Part 3 closure |
| 923 | `--audio-source-container` | Not yet mapped; classify before Part 3 closure |
| 929 | `--audio-source-fallback` | Not yet mapped; classify before Part 3 closure |
| 936 | `--no-audio-source-fallback` | Not yet mapped; classify before Part 3 closure |
| 942 | `--audio-format` | Rust subset implemented; parity review required |
| 948 | `--audio-quality` | Rust subset implemented; parity review required |
| 954 | `--write-subs` | Not yet mapped; classify before Part 3 closure |
| 961 | `--no-write-subs` | Not yet mapped; classify before Part 3 closure |
| 968 | `--write-auto-subs` | Not yet mapped; classify before Part 3 closure |
| 975 | `--no-write-auto-subs` | Not yet mapped; classify before Part 3 closure |
| 981 | `--sub-langs` | Not yet mapped; classify before Part 3 closure |
| 986 | `--sub-format` | Not yet mapped; classify before Part 3 closure |
| 992 | `--embed-subs` | Not yet mapped; classify before Part 3 closure |
| 999 | `--no-embed-subs` | Not yet mapped; classify before Part 3 closure |
| 1006 | `--write-thumbnail` | Not yet mapped; classify before Part 3 closure |
| 1013 | `--no-write-thumbnail` | Not yet mapped; classify before Part 3 closure |
| 1020 | `--embed-thumbnail` | Rust subset implemented; parity review required |
| 1027 | `--no-embed-thumbnail` | Rust subset implemented; parity review required |
| 1034 | `--write-info-json` | Not yet mapped; classify before Part 3 closure |
| 1041 | `--no-write-info-json` | Not yet mapped; classify before Part 3 closure |
| 1048 | `--embed-metadata` | Rust subset implemented; parity review required |
| 1055 | `--no-embed-metadata` | Rust subset implemented; parity review required |
| 1062 | `--embed-chapters` | Rust subset implemented; parity review required |
| 1069 | `--no-embed-chapters` | Rust subset implemented; parity review required |
| 1076 | `--sponsorblock` | Not yet mapped; classify before Part 3 closure |
| 1083 | `--no-sponsorblock` | Not yet mapped; classify before Part 3 closure |
| 1089 | `--sponsorblock-mark` | Not yet mapped; classify before Part 3 closure |
| 1094 | `--sponsorblock-remove` | Not yet mapped; classify before Part 3 closure |
| 1100 | `--live` | Not yet mapped; classify before Part 3 closure |
| 1107 | `--no-live` | Not yet mapped; classify before Part 3 closure |
| 1114 | `--live-from-start` | Not yet mapped; classify before Part 3 closure |
| 1121 | `--live-edge`, `--no-live-from-start` | Not yet mapped; classify before Part 3 closure |
| 1128 | `--wait-for-video` | Not yet mapped; classify before Part 3 closure |
| 1133 | `--no-wait-for-video` | Not yet mapped; classify before Part 3 closure |
| 1140 | `--write-live-chat` | Not yet mapped; classify before Part 3 closure |
| 1147 | `--no-write-live-chat` | Not yet mapped; classify before Part 3 closure |
| 1153 | `--chapter-section` | Not yet mapped; classify before Part 3 closure |
| 1162 | `--time-range` | Not yet mapped; classify before Part 3 closure |
| 1173 | `--whole-item` | Not yet mapped; classify before Part 3 closure |
| 1178 | `--limit-rate` | Not yet mapped; classify before Part 3 closure |
| 1183 | `--throttled-rate` | Not yet mapped; classify before Part 3 closure |
| 1188 | `--user-agent` | Not yet mapped; classify before Part 3 closure |
| 1194 | `--impersonate` | Not yet mapped; classify before Part 3 closure |
| 1199 | `--no-impersonate` | Not yet mapped; classify before Part 3 closure |
| 1204 | `--referer` | Not yet mapped; classify before Part 3 closure |
| 1209 | `--add-header` | Not yet mapped; classify before Part 3 closure |
| 1216 | `--proxy` | Not yet mapped; classify before Part 3 closure |
| 1221 | `--socket-timeout` | Not yet mapped; classify before Part 3 closure |
| 1227 | `--source-address` | Not yet mapped; classify before Part 3 closure |
| 1233 | `--force-ipv4` | Not yet mapped; classify before Part 3 closure |
| 1240 | `--force-ipv6` | Not yet mapped; classify before Part 3 closure |
| 1247 | `-N`, `--concurrent-fragments` | Not yet mapped; classify before Part 3 closure |
| 1254 | `-R`, `--retries` | Not yet mapped; classify before Part 3 closure |
| 1260 | `--fragment-retries` | Not yet mapped; classify before Part 3 closure |
| 1265 | `--file-access-retries` | Not yet mapped; classify before Part 3 closure |
| 1270 | `--extractor-retries` | Not yet mapped; classify before Part 3 closure |
| 1275 | `--retry-sleep` | Not yet mapped; classify before Part 3 closure |
| 1281 | `--archive` | Not yet mapped; classify before Part 3 closure |
| 1287 | `--temp-path` | Not yet mapped; classify before Part 3 closure |
| 1293 | `--extractor-args` | Not yet mapped; classify before Part 3 closure |
| 1299 | `--playlist-index` | Not yet mapped; classify before Part 3 closure |
| 1309 | `--playlist-range` | Not yet mapped; classify before Part 3 closure |
| 1318 | `--playlist-slice` | Not yet mapped; classify before Part 3 closure |
| 1326 | `--rev`, `--reverse-playlist` | Not yet mapped; classify before Part 3 closure |
| 1334 | `--playlist-forward`, `--no-reverse-playlist` | Not yet mapped; classify before Part 3 closure |
| 1342 | `--playlist` | Rust subset implemented; parity review required |
| 1349 | `--no-playlist` | Rust subset implemented; parity review required |
| 1355 | `--input-file` | Not yet mapped; classify before Part 3 closure |
| 1361 | `--collection-file` | Not yet mapped; classify before Part 3 closure |
| 1370 | `--collection-continuation-ignore` | Not yet mapped; classify before Part 3 closure |
| 1375 | `--collection-continuation-reset` | Not yet mapped; classify before Part 3 closure |
| 1380 | `--collection-continuation-status` | Not yet mapped; classify before Part 3 closure |
| 1386 | `--cookies` | Not yet mapped; classify before Part 3 closure |
| 1395 | `--cookies-from-browser` | Not yet mapped; classify before Part 3 closure |
| 1400 | `--no-cookies` | Not yet mapped; classify before Part 3 closure |
| 1406 | `--auto-cookies` | Not yet mapped; classify before Part 3 closure |
| 1413 | `--explain` | Not yet mapped; classify before Part 3 closure |
| 1418 | `--explain-json` | Not yet mapped; classify before Part 3 closure |
| 1423 | `--dry-run` | Not yet mapped; classify before Part 3 closure |
| 1428 | `--debug-external` | Not yet mapped; classify before Part 3 closure |
| 1433 | `--debug-external-unsafe` | Not yet mapped; classify before Part 3 closure |
| 1439 | `--remove-completed-ids` | Not yet mapped; classify before Part 3 closure |
| 1448 | `--remove-completed-rows` | Not yet mapped; classify before Part 3 closure |
| 1457 | `--queue-report` | Not yet mapped; classify before Part 3 closure |
| 1465 | `--failed-targets` | Not yet mapped; classify before Part 3 closure |
| 1474 | `--run-manifest` | Not yet mapped; classify before Part 3 closure |
| 1480 | `--hash-outputs` | Not yet mapped; classify before Part 3 closure |
| 1485 | `--_remove-completed-id` | Not yet mapped; classify before Part 3 closure |
| 1491 | `--_remove-completed-row` | Not yet mapped; classify before Part 3 closure |
| 1497 | `--_record-collection-completion` | Not yet mapped; classify before Part 3 closure |
| 1503 | `--_record-output` | Not yet mapped; classify before Part 3 closure |
| 1509 | `--examples` | Not yet mapped; classify before Part 3 closure |
| 1514 | `--version` | Not yet mapped; classify before Part 3 closure |

Total parser definitions: **116**. The inventory includes positional arguments. It does not count dynamically generated parser options or options registered outside direct `add_argument` calls.

Before Part 3 closure, classify every currently unmapped row by actual Python behaviour and assign it to the Rust CLI subset or a named later execution/backend part. Do not treat an unimplemented execution option as an implemented native capability.

## Explicit ownership disposition

The following assignments distinguish **parser accounting** from **implemented functionality**. A later-part assignment does not mean Rust currently accepts the switch, and does not authorise silently ignoring it. Until that part implements the option, the Rust CLI must reject it rather than report success. Part 3 remains responsible for ensuring the current supported subset parses consistently and for documenting each unsupported option.

| Python line | Switch(es) | Assigned ownership |
| ---: | --- | --- |
| 782 | `targets` | Part 7: execution target; Part 3 rejects unsupported execution |
| 788 | `-p`, `--profile`, `--parameter-profile` | Part 3: inspection/configuration contract |
| 796 | `-d`, `--defaults` | Part 3: inspection/configuration contract |
| 803 | `--list-profiles`, `--list-parameters` | Part 3: inspection/configuration contract |
| 810 | `--profile-tree` | Part 3: inspection/configuration contract |
| 817 | `--schema-json` | Part 3: inspection/configuration contract |
| 822 | `--validate-config` | Part 3: inspection/configuration contract |
| 829 | `--capabilities` | Part 3: parse/exclusivity; Parts 4-5: truthful report content |
| 834 | `--capabilities-json` | Part 3: parse/exclusivity; Parts 4-5: truthful report content |
| 839 | `-r`, `--resolution` | Part 6: media and format planning |
| 849 | `-f`, `--format` | Part 6: media and format planning |
| 860 | `--min-resolution` | Part 6: media and format planning |
| 865 | `--max-resolution` | Part 6: media and format planning |
| 870 | `--min-fps` | Part 6: media and format planning |
| 871 | `--max-fps` | Part 6: media and format planning |
| 872 | `--preferred-fps` | Part 6: media and format planning |
| 875 | `--preferred-video-codec` | Part 6: media and format planning |
| 880 | `--preferred-audio-codec` | Part 6: media and format planning |
| 885 | `--preferred-hdr` | Part 6: media and format planning |
| 890 | `--preferred-audio-channels` | Part 6: media and format planning |
| 896 | `--merge-container` | Part 6: media and format planning |
| 905 | `--audio-only` | Part 3: typed setting subset; Part 6 consumes it |
| 912 | `--no-audio-only` | Part 3: typed setting subset; Part 6 consumes it |
| 918 | `--audio-source-codec` | Part 6: media and format planning |
| 923 | `--audio-source-container` | Part 6: media and format planning |
| 929 | `--audio-source-fallback` | Part 6: media and format planning |
| 936 | `--no-audio-source-fallback` | Part 6: media and format planning |
| 942 | `--audio-format` | Part 3: typed setting subset; Part 6 consumes it |
| 948 | `--audio-quality` | Part 3: typed setting subset; Part 6 consumes it |
| 954 | `--write-subs` | Part 7: download/post-processing execution |
| 961 | `--no-write-subs` | Part 7: download/post-processing execution |
| 968 | `--write-auto-subs` | Part 7: download/post-processing execution |
| 975 | `--no-write-auto-subs` | Part 7: download/post-processing execution |
| 981 | `--sub-langs` | Part 7: download/post-processing execution |
| 986 | `--sub-format` | Part 7: download/post-processing execution |
| 992 | `--embed-subs` | Part 7: download/post-processing execution |
| 999 | `--no-embed-subs` | Part 7: download/post-processing execution |
| 1006 | `--write-thumbnail` | Part 7: download/post-processing execution |
| 1013 | `--no-write-thumbnail` | Part 7: download/post-processing execution |
| 1020 | `--embed-thumbnail` | Part 3: typed setting subset; Part 7 consumes it |
| 1027 | `--no-embed-thumbnail` | Part 3: typed setting subset; Part 7 consumes it |
| 1034 | `--write-info-json` | Part 7: download/post-processing execution |
| 1041 | `--no-write-info-json` | Part 7: download/post-processing execution |
| 1048 | `--embed-metadata` | Part 3: typed setting subset; Part 7 consumes it |
| 1055 | `--no-embed-metadata` | Part 3: typed setting subset; Part 7 consumes it |
| 1062 | `--embed-chapters` | Part 3: typed setting subset; Part 7 consumes it |
| 1069 | `--no-embed-chapters` | Part 3: typed setting subset; Part 7 consumes it |
| 1076 | `--sponsorblock` | Part 7: download/post-processing execution |
| 1083 | `--no-sponsorblock` | Part 7: download/post-processing execution |
| 1089 | `--sponsorblock-mark` | Part 7: download/post-processing execution |
| 1094 | `--sponsorblock-remove` | Part 7: download/post-processing execution |
| 1100 | `--live` | Part 7: live and section execution |
| 1107 | `--no-live` | Part 7: live and section execution |
| 1114 | `--live-from-start` | Part 7: live and section execution |
| 1121 | `--live-edge`, `--no-live-from-start` | Part 7: live and section execution |
| 1128 | `--wait-for-video` | Part 7: live and section execution |
| 1133 | `--no-wait-for-video` | Part 7: live and section execution |
| 1140 | `--write-live-chat` | Part 7: live and section execution |
| 1147 | `--no-write-live-chat` | Part 7: live and section execution |
| 1153 | `--chapter-section` | Part 7: live and section execution |
| 1162 | `--time-range` | Part 7: live and section execution |
| 1173 | `--whole-item` | Part 7: live and section execution |
| 1178 | `--limit-rate` | Part 7: transfer/runtime controls |
| 1183 | `--throttled-rate` | Part 7: transfer/runtime controls |
| 1188 | `--user-agent` | Part 5: backend integration and acquisition controls |
| 1194 | `--impersonate` | Part 5: backend integration and acquisition controls |
| 1199 | `--no-impersonate` | Part 5: backend integration and acquisition controls |
| 1204 | `--referer` | Part 5: backend integration and acquisition controls |
| 1209 | `--add-header` | Part 5: backend integration and acquisition controls |
| 1216 | `--proxy` | Part 5: backend integration and acquisition controls |
| 1221 | `--socket-timeout` | Part 5: backend integration and acquisition controls |
| 1227 | `--source-address` | Part 5: backend integration and acquisition controls |
| 1233 | `--force-ipv4` | Part 5: backend integration and acquisition controls |
| 1240 | `--force-ipv6` | Part 5: backend integration and acquisition controls |
| 1247 | `-N`, `--concurrent-fragments` | Part 7: transfer/runtime controls |
| 1254 | `-R`, `--retries` | Part 7: transfer/runtime controls |
| 1260 | `--fragment-retries` | Part 7: transfer/runtime controls |
| 1265 | `--file-access-retries` | Part 7: transfer/runtime controls |
| 1270 | `--extractor-retries` | Part 7: transfer/runtime controls |
| 1275 | `--retry-sleep` | Part 7: transfer/runtime controls |
| 1281 | `--archive` | Part 7: download persistence/runtime |
| 1287 | `--temp-path` | Part 7: download persistence/runtime |
| 1293 | `--extractor-args` | Part 5: backend extractor integration |
| 1299 | `--playlist-index` | Part 7: playlist/queue execution |
| 1309 | `--playlist-range` | Part 7: playlist/queue execution |
| 1318 | `--playlist-slice` | Part 7: playlist/queue execution |
| 1326 | `--rev`, `--reverse-playlist` | Part 7: playlist/queue execution |
| 1334 | `--playlist-forward`, `--no-reverse-playlist` | Part 7: playlist/queue execution |
| 1342 | `--playlist` | Part 3: typed setting subset; Part 7 consumes it |
| 1349 | `--no-playlist` | Part 3: typed setting subset; Part 7 consumes it |
| 1355 | `--input-file` | Part 7: collection and cookie execution |
| 1361 | `--collection-file` | Part 7: collection and cookie execution |
| 1370 | `--collection-continuation-ignore` | Part 7: collection and cookie execution |
| 1375 | `--collection-continuation-reset` | Part 7: collection and cookie execution |
| 1380 | `--collection-continuation-status` | Part 7: collection and cookie execution |
| 1386 | `--cookies` | Part 5: backend cookie integration |
| 1395 | `--cookies-from-browser` | Part 5: backend cookie integration |
| 1400 | `--no-cookies` | Part 5: backend cookie integration |
| 1406 | `--auto-cookies` | Part 5: backend cookie integration |
| 1413 | `--explain` | Part 4: execution-plan diagnostics |
| 1418 | `--explain-json` | Part 4: execution-plan diagnostics |
| 1423 | `--dry-run` | Part 4: execution-plan diagnostics |
| 1428 | `--debug-external` | Part 4: execution-plan diagnostics |
| 1433 | `--debug-external-unsafe` | Part 5: backend diagnostics |
| 1439 | `--remove-completed-ids` | Part 7: queue/output completion and bookkeeping |
| 1448 | `--remove-completed-rows` | Part 7: queue/output completion and bookkeeping |
| 1457 | `--queue-report` | Part 7: queue/output completion and bookkeeping |
| 1465 | `--failed-targets` | Part 7: queue/output completion and bookkeeping |
| 1474 | `--run-manifest` | Part 7: queue/output completion and bookkeeping |
| 1480 | `--hash-outputs` | Part 7: queue/output completion and bookkeeping |
| 1485 | `--_remove-completed-id` | Part 7: queue/output completion and bookkeeping |
| 1491 | `--_remove-completed-row` | Part 7: queue/output completion and bookkeeping |
| 1497 | `--_record-collection-completion` | Part 7: queue/output completion and bookkeeping |
| 1503 | `--_record-output` | Part 7: queue/output completion and bookkeeping |
| 1509 | `--examples` | Part 3: informational CLI |
| 1514 | `--version` | Part 3: informational CLI |

This is a planning disposition, not a complete semantic equivalence proof. Cross-setting constraints, exact argparse error messages, and the terminal encoding fallback remain outstanding Part 3 verification work. The internal underscore-prefixed bookkeeping switches are execution-private and must not be exposed as successful no-ops.
