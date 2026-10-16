# Python Downloader argument inventory

This inventory is extracted from the `add_argument` calls in the packaged `yt-download.py` source using Python AST parsing. It is an accounting aid, not proof of CLI parity. Flags in the same row are aliases of one parser definition. The source line is provided for review.

| Python source line | Argument spellings | Rust implementation status |
| ---: | --- | --- |
| 782 | `targets` | Target handling planned for Part 4; execution deferred |
| 788 | `-p`, `--profile`, `--parameter-profile` | Implemented bounded subset; retain regression coverage |
| 796 | `-d`, `--defaults` | Implemented bounded subset; retain regression coverage |
| 803 | `--list-profiles`, `--list-parameters` | Implemented bounded subset; retain regression coverage |
| 810 | `--profile-tree` | Implemented bounded subset; retain regression coverage |
| 817 | `--schema-json` | Implemented bounded subset; retain regression coverage |
| 822 | `--validate-config` | Implemented bounded subset; retain regression coverage |
| 829 | `--capabilities` | Argument constraints implemented; report content deferred to Parts 4–5 |
| 834 | `--capabilities-json` | Argument constraints implemented; report content deferred to Parts 4–5 |
| 839 | `-r`, `--resolution` | Deferred; see ownership disposition |
| 849 | `-f`, `--format` | Deferred; see ownership disposition |
| 860 | `--min-resolution` | Deferred; see ownership disposition |
| 865 | `--max-resolution` | Deferred; see ownership disposition |
| 870 | `--min-fps` | Deferred; see ownership disposition |
| 871 | `--max-fps` | Deferred; see ownership disposition |
| 872 | `--preferred-fps` | Deferred; see ownership disposition |
| 875 | `--preferred-video-codec` | Deferred; see ownership disposition |
| 880 | `--preferred-audio-codec` | Deferred; see ownership disposition |
| 885 | `--preferred-hdr` | Deferred; see ownership disposition |
| 890 | `--preferred-audio-channels` | Deferred; see ownership disposition |
| 896 | `--merge-container` | Deferred; see ownership disposition |
| 905 | `--audio-only` | Implemented bounded subset; retain regression coverage |
| 912 | `--no-audio-only` | Implemented bounded subset; retain regression coverage |
| 918 | `--audio-source-codec` | Deferred; see ownership disposition |
| 923 | `--audio-source-container` | Deferred; see ownership disposition |
| 929 | `--audio-source-fallback` | Deferred; see ownership disposition |
| 936 | `--no-audio-source-fallback` | Deferred; see ownership disposition |
| 942 | `--audio-format` | Implemented bounded subset; retain regression coverage |
| 948 | `--audio-quality` | Implemented bounded subset; retain regression coverage |
| 954 | `--write-subs` | Deferred; see ownership disposition |
| 961 | `--no-write-subs` | Deferred; see ownership disposition |
| 968 | `--write-auto-subs` | Deferred; see ownership disposition |
| 975 | `--no-write-auto-subs` | Deferred; see ownership disposition |
| 981 | `--sub-langs` | Deferred; see ownership disposition |
| 986 | `--sub-format` | Deferred; see ownership disposition |
| 992 | `--embed-subs` | Deferred; see ownership disposition |
| 999 | `--no-embed-subs` | Deferred; see ownership disposition |
| 1006 | `--write-thumbnail` | Deferred; see ownership disposition |
| 1013 | `--no-write-thumbnail` | Deferred; see ownership disposition |
| 1020 | `--embed-thumbnail` | Implemented bounded subset; retain regression coverage |
| 1027 | `--no-embed-thumbnail` | Implemented bounded subset; retain regression coverage |
| 1034 | `--write-info-json` | Deferred; see ownership disposition |
| 1041 | `--no-write-info-json` | Deferred; see ownership disposition |
| 1048 | `--embed-metadata` | Implemented bounded subset; retain regression coverage |
| 1055 | `--no-embed-metadata` | Implemented bounded subset; retain regression coverage |
| 1062 | `--embed-chapters` | Implemented bounded subset; retain regression coverage |
| 1069 | `--no-embed-chapters` | Implemented bounded subset; retain regression coverage |
| 1076 | `--sponsorblock` | Deferred; see ownership disposition |
| 1083 | `--no-sponsorblock` | Deferred; see ownership disposition |
| 1089 | `--sponsorblock-mark` | Deferred; see ownership disposition |
| 1094 | `--sponsorblock-remove` | Deferred; see ownership disposition |
| 1100 | `--live` | Deferred; see ownership disposition |
| 1107 | `--no-live` | Deferred; see ownership disposition |
| 1114 | `--live-from-start` | Deferred; see ownership disposition |
| 1121 | `--live-edge`, `--no-live-from-start` | Deferred; see ownership disposition |
| 1128 | `--wait-for-video` | Deferred; see ownership disposition |
| 1133 | `--no-wait-for-video` | Deferred; see ownership disposition |
| 1140 | `--write-live-chat` | Deferred; see ownership disposition |
| 1147 | `--no-write-live-chat` | Deferred; see ownership disposition |
| 1153 | `--chapter-section` | Deferred; see ownership disposition |
| 1162 | `--time-range` | Deferred; see ownership disposition |
| 1173 | `--whole-item` | Deferred; see ownership disposition |
| 1178 | `--limit-rate` | Deferred; see ownership disposition |
| 1183 | `--throttled-rate` | Deferred; see ownership disposition |
| 1188 | `--user-agent` | Deferred; see ownership disposition |
| 1194 | `--impersonate` | Deferred; see ownership disposition |
| 1199 | `--no-impersonate` | Deferred; see ownership disposition |
| 1204 | `--referer` | Deferred; see ownership disposition |
| 1209 | `--add-header` | Deferred; see ownership disposition |
| 1216 | `--proxy` | Deferred; see ownership disposition |
| 1221 | `--socket-timeout` | Deferred; see ownership disposition |
| 1227 | `--source-address` | Deferred; see ownership disposition |
| 1233 | `--force-ipv4` | Deferred; see ownership disposition |
| 1240 | `--force-ipv6` | Deferred; see ownership disposition |
| 1247 | `-N`, `--concurrent-fragments` | Deferred; see ownership disposition |
| 1254 | `-R`, `--retries` | Deferred; see ownership disposition |
| 1260 | `--fragment-retries` | Deferred; see ownership disposition |
| 1265 | `--file-access-retries` | Deferred; see ownership disposition |
| 1270 | `--extractor-retries` | Deferred; see ownership disposition |
| 1275 | `--retry-sleep` | Deferred; see ownership disposition |
| 1281 | `--archive` | Deferred; see ownership disposition |
| 1287 | `--temp-path` | Deferred; see ownership disposition |
| 1293 | `--extractor-args` | Deferred; see ownership disposition |
| 1299 | `--playlist-index` | Deferred; see ownership disposition |
| 1309 | `--playlist-range` | Deferred; see ownership disposition |
| 1318 | `--playlist-slice` | Deferred; see ownership disposition |
| 1326 | `--rev`, `--reverse-playlist` | Deferred; see ownership disposition |
| 1334 | `--playlist-forward`, `--no-reverse-playlist` | Deferred; see ownership disposition |
| 1342 | `--playlist` | Implemented bounded subset; retain regression coverage |
| 1349 | `--no-playlist` | Implemented bounded subset; retain regression coverage |
| 1355 | `--input-file` | Deferred; see ownership disposition |
| 1361 | `--collection-file` | Deferred; see ownership disposition |
| 1370 | `--collection-continuation-ignore` | Deferred; see ownership disposition |
| 1375 | `--collection-continuation-reset` | Deferred; see ownership disposition |
| 1380 | `--collection-continuation-status` | Deferred; see ownership disposition |
| 1386 | `--cookies` | Deferred; see ownership disposition |
| 1395 | `--cookies-from-browser` | Deferred; see ownership disposition |
| 1400 | `--no-cookies` | Deferred; see ownership disposition |
| 1406 | `--auto-cookies` | Deferred; see ownership disposition |
| 1413 | `--explain` | Deferred; see ownership disposition |
| 1418 | `--explain-json` | Deferred; see ownership disposition |
| 1423 | `--dry-run` | Deferred; see ownership disposition |
| 1428 | `--debug-external` | Deferred; see ownership disposition |
| 1433 | `--debug-external-unsafe` | Deferred; see ownership disposition |
| 1439 | `--remove-completed-ids` | Deferred; see ownership disposition |
| 1448 | `--remove-completed-rows` | Deferred; see ownership disposition |
| 1457 | `--queue-report` | Deferred; see ownership disposition |
| 1465 | `--failed-targets` | Deferred; see ownership disposition |
| 1474 | `--run-manifest` | Deferred; see ownership disposition |
| 1480 | `--hash-outputs` | Deferred; see ownership disposition |
| 1485 | `--_remove-completed-id` | Deferred; see ownership disposition |
| 1491 | `--_remove-completed-row` | Deferred; see ownership disposition |
| 1497 | `--_record-collection-completion` | Deferred; see ownership disposition |
| 1503 | `--_record-output` | Deferred; see ownership disposition |
| 1509 | `--examples` | Deferred; see ownership disposition |
| 1514 | `--version` | Deferred; see ownership disposition |

Total parser definitions: **116**. The inventory includes positional arguments. It does not count dynamically generated parser options or options registered outside direct `add_argument` calls.

The ownership disposition below assigns deferred options to later implementation work. An assignment is not an assertion of native support.

## Explicit ownership disposition

The following assignments distinguish **parser accounting** from **implemented functionality**. A later-part assignment does not mean Rust currently accepts the switch, and does not authorise silently ignoring it. Until that part implements the option, the Rust CLI must reject it rather than report success. The supported subset remains covered by regression tests, and unsupported options must remain explicit.

| Python line | Switch(es) | Assigned ownership |
| ---: | --- | --- |
| 782 | `targets` | Part 4: target handling and execution planning; actual downloads deferred |
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

This is a planning disposition, not a complete semantic equivalence proof. Cross-setting constraints, exact argparse error messages and terminal encoding differences remain ongoing compatibility concerns. The internal underscore-prefixed bookkeeping switches are execution-private and must not be exposed as successful no-ops.
