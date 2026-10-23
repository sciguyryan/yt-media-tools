"""Regenerate or check the portable heterogeneous facet fixture."""

from __future__ import annotations

import argparse
import json

from validate_portable_facets import PATH, ROOT, validate

SOURCE = ROOT / "yt-sql/datasets/heterogeneous-sources-v1.json"


def generate() -> dict:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    facets = [
        {"source": "@youtube_channel", "name": "videos", "record_indices": [0, 1]},
        {"source": "@youtube_channel", "name": "shorts", "record_indices": []},
        {"source": "@youtube_playlist", "name": "videos", "record_indices": [2, 3]},
        {"source": "@youtube_playlist", "name": "live", "record_indices": []},
        {"source": "@twitch_archive", "name": "videos", "record_indices": []},
        {"source": "@twitch_archive", "name": "streams", "record_indices": [4, 5]},
    ]
    result = {key: source[key] for key in ("version", "record_count", "record_digest_sha256", "records", "sources")}
    result.update(
        id="heterogeneous-facets-v1",
        kind="facet-topology",
        provenance={"source_dataset": "heterogeneous-sources-v1"},
        facets=facets,
    )
    validate(result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = json.dumps(generate(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.check:
        if not PATH.exists() or PATH.read_text(encoding="utf-8") != expected:
            print(f"{PATH.relative_to(ROOT)} needs regeneration")
            return 1
        print(f"{PATH.relative_to(ROOT)} is current")
    else:
        PATH.write_text(expected, encoding="utf-8")
        print(f"Exported {PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
