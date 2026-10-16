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
