"""Generate deterministic extractor-like datasets for yt-sql conformance testing.

The generator does not parse or evaluate yt-sql. It produces logical metadata records
and can seed a real yt-discover cache. Normal pytest runs create datasets ephemerally;
this CLI remains available for inspection, reproduction, stress testing and benchmarks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from yt_media_tools.cache import MetadataCache  # noqa: E402

GENERATOR_VERSION = 3
DATASET_SEED = 31415926
SOURCE_HANDLE = "@yt_sql_fixture"
SOURCE_URL = "https://www.youtube.com/@yt_sql_fixture/videos"
GENERATED_AT = "2026-09-01T12:00:00+00:00"

# Keep the deliberately hand-designed anchor corpus small enough for semantic tests,
# while larger profiles are substantial enough to reveal scaling and performance bugs.
PROFILE_SIZES: dict[str, int] = {
    "small": 60,
    "normal": 1_000,
    "large": 10_000,
    "huge": 100_000,
}


def _epoch(iso_text: str) -> int:
    return int(datetime.fromisoformat(iso_text.replace("Z", "+00:00")).timestamp())


def _anchor_records(seed: int) -> list[dict[str, object]]:
    """Return the hand-designed semantic anchor records.

    These records deliberately encode exact boundaries, awkward values and Unicode
    edge cases. Larger datasets retain this prefix and extend it with deterministic
    generated records.
    """
    rng = random.Random(seed)
    specs = [
        ("vid001", "Mars: New Dawn", "20260831", "2026-08-31T20:30:00Z", 3599, 1_500_000, "public", None),
        ("vid002", "mars: new dawn", "20260831", "2026-08-31T08:15:00Z", 3600, 1_500_000, "public", None),
        ("vid003", "Venus Weather", "20260830", "2026-08-30T17:00:00Z", 3601, 250_000, "public", None),
        ("vid004", "Mars [LIVE]", "20260830", "2026-08-30T09:00:00Z", 900, 2_000_000, "public", "was_live"),
        ("vid005", "Jupiter Update", "20260829", "2026-08-29T12:00:00Z", 0, 0, "public", None),
        ("vid006", "Untitled?", "20260828", None, None, None, "public", None),
        ("vid007", "MARS geology", "20260827", "2026-08-27T23:59:59Z", 600, 999_999, "public", None),
        ("vid008", "Moon & Mars", "20260827", "2026-08-27T00:00:01Z", 600, 1_000_000, "public", None),
        ("vid009", "Duplicate", "20260826", "2026-08-26T18:00:00Z", 1200, 42, "public", None),
        ("vid010", "Duplicate", "20260826", "2026-08-26T06:00:00Z", 1200, 42, "public", None),
        ("vid011", "Regex .* literal", "20260825", "2026-08-25T10:00:00Z", 1800, 12_345, "public", None),
        ("vid012", "100% Mars", "20260824", "2026-08-24T10:00:00Z", 1801, 54_321, "public", None),
        ("vid013", "O'Brien on Mars", "20260823", "2026-08-23T10:00:00Z", 30, 7, "public", None),
        ("vid014", "Unicode café Δ", "20260822", "2026-08-22T10:00:00Z", 7200, 88_888, "public", None),
        ("vid015", "Private observation", "20260821", "2026-08-21T10:00:00Z", 300, 10, "private", None),
        ("vid016", "Members observation", "20260820", "2026-08-20T10:00:00Z", 301, 11, "subscriber_only", None),
        ("vid017", "Upcoming Mars", "20260819", "2026-08-19T10:00:00Z", 0, 0, "public", "is_upcoming"),
        ("vid018", "Ancient Mars", "20260818", "2026-08-18T10:00:00Z", 86399, 5_000_000, "public", None),
        ("vid019", "One day exactly", "20260817", "2026-08-17T10:00:00Z", 86400, 123, "public", None),
        ("vid020", "One day plus", "20260816", "2026-08-16T10:00:00Z", 86401, 124, "public", None),
        ("vid021", "Zero views", "20260815", "2026-08-15T10:00:00Z", 59, 0, "public", None),
        ("vid022", "Null views", "20260814", "2026-08-14T10:00:00Z", 60, None, "public", None),
        ("vid023", "Case Test", "20260813", "2026-08-13T10:00:00Z", 61, 100, "public", None),
        ("vid024", "case test", "20260812", "2026-08-12T10:00:00Z", 62, 101, "public", None),
        ("vid025", "Tie A", "20260811", "2026-08-11T10:00:00Z", 1000, 500, "public", None),
        ("vid026", "Tie B", "20260811", "2026-08-11T10:00:00Z", 1000, 500, "public", None),
        ("vid027", "Boundary start", "20260801", "2026-08-01T00:00:00Z", 1, 1, "public", None),
        ("vid028", "Before boundary", "20260731", "2026-07-31T23:59:59Z", 2, 2, "public", None),
        ("vid029", "Year start", "20260101", "2026-01-01T00:00:00Z", 3, 3, "public", None),
        ("vid030", "Leap-era sample", "20240229", "2024-02-29T12:00:00Z", 4, 4, "public", None),
        ("vid031", "No upload date", None, "2026-08-10T12:00:00Z", 5, 5, "public", None),
        ("vid032", "No timestamp", "20260810", None, 6, 6, "public", None),
        ("vid033", "Boolean live", "20260809", "2026-08-09T12:00:00Z", 7, 7, "public", "is_live"),
        ("vid034", "Large count", "20260808", "2026-08-08T12:00:00Z", 8, 9_223_372_036, "public", None),
        ("vid035", "Empty title sentinel", "20260807", "2026-08-07T12:00:00Z", 9, 9, None, None),
        ("vid036", "Final source row", "20260806", "2026-08-06T12:00:00Z", 10, 10, "public", None),
        ("vid037", "Café composed é", "20260805", "2026-08-05T12:00:00Z", 11, 11, "public", None),
        ("vid038", "Café decomposed é", "20260804", "2026-08-04T12:00:00Z", 12, 12, "public", None),
        ("vid039", "Combining only ̧́", "20260803", "2026-08-03T12:00:00Z", 13, 13, "public", None),
        ("vid040", "Emoji 😀", "20260802", "2026-08-02T12:00:00Z", 14, 14, "public", None),
        ("vid041", "Emoji family 👩‍👩‍👧‍👦", "20260730", "2026-07-30T12:00:00Z", 15, 15, "public", None),
        ("vid042", "Flag 🏴󠁧󠁢󠁷󠁬󠁳󠁿", "20260729", "2026-07-29T12:00:00Z", 16, 16, "public", None),
        ("vid043", "Variation ✈️", "20260728", "2026-07-28T12:00:00Z", 17, 17, "public", None),
        ("vid044", "Greek Σ σ ς", "20260727", "2026-07-27T12:00:00Z", 18, 18, "public", None),
        ("vid045", "Turkish İ I ı i", "20260726", "2026-07-26T12:00:00Z", 19, 19, "public", None),
        ("vid046", "German Straße STRASSE", "20260725", "2026-07-25T12:00:00Z", 20, 20, "public", None),
        ("vid047", "Kelvin K K k", "20260724", "2026-07-24T12:00:00Z", 21, 21, "public", None),
        ("vid048", "Long s ſ S", "20260723", "2026-07-23T12:00:00Z", 22, 22, "public", None),
        ("vid049", "CJK 東京漢字", "20260722", "2026-07-22T12:00:00Z", 23, 23, "public", None),
        ("vid050", "Arabic مرحبا", "20260721", "2026-07-21T12:00:00Z", 24, 24, "public", None),
        ("vid051", "Hebrew שלום", "20260720", "2026-07-20T12:00:00Z", 25, 25, "public", None),
        ("vid052", "NBSP space", "20260719", "2026-07-19T12:00:00Z", 26, 26, "public", None),
        ("vid053", "Thin space", "20260718", "2026-07-18T12:00:00Z", 27, 27, "public", None),
        ("vid054", "RTL mark ‏text", "20260717", "2026-07-17T12:00:00Z", 28, 28, "public", None),
        ("vid055", "Wildcards % _ \\ and fullwidth ％＿", "20260716", "2026-07-16T12:00:00Z", 29, 29, "public", None),
        ("vid056", "Astral 𐐷 𝄞", "20260715", "2026-07-15T12:00:00Z", 30, 30, "public", None),
        ("vid057", "Line\nbreak", "20260714", "2026-07-14T12:00:00Z", 31, 31, "public", None),
        ("vid058", "Line separator \u2028", "20260713", "2026-07-13T12:00:00Z", 32, 32, "public", None),
        ("vid059", "Zero width joiner A‍B", "20260712", "2026-07-12T12:00:00Z", 33, 33, "public", None),
        ("vid060", "Zero width non-joiner A‌B", "20260711", "2026-07-11T12:00:00Z", 34, 34, "public", None),
    ]

    rows: list[dict[str, object]] = []
    for index, (media_id, title, upload_date, release_iso, duration, views, availability, live_status) in enumerate(
        specs, start=1
    ):
        rows.append(
            {
                "id": media_id,
                "title": title,
                "upload_date": upload_date,
                "release_timestamp": _epoch(release_iso) if release_iso else None,
                "timestamp": _epoch(release_iso) if release_iso else None,
                "duration": duration,
                "view_count": views,
                "like_count": None if views is None else rng.randint(0, 10_000),
                "comment_count": None if views is None else rng.randint(0, 2_000),
                "availability": availability,
                "live_status": live_status,
                "is_live": live_status == "is_live",
                "was_live": live_status == "was_live",
                "channel_id": "fixture-channel",
                "channel": "Conformance Fixture",
                "uploader": "Conformance Fixture",
                "webpage_url": f"https://fixture.invalid/watch/{media_id}",
                "fixture_group": index % 4,
                "fixture_nullable": None if index % 5 == 0 else f"g{index % 3}",
            }
        )
    return rows


def _generated_record(index: int, rng: random.Random) -> dict[str, object]:
    """Create one deterministic extension record with controlled distributions."""
    # Extension records become progressively older, preserving newest-first source order.
    release = datetime(2026, 8, 5, 23, 0, tzinfo=timezone.utc) - timedelta(hours=index - 37)
    media_id = f"media{index:09d}"

    topics = ("Mars", "Venus", "Jupiter", "Saturn", "Moon", "Comet", "Nebula", "Quasar")
    title = f"{topics[index % len(topics)]} synthetic observation {index:09d}"
    if index % 97 == 0:
        title = f"Duplicate generated title {index % 7}"
    elif index % 131 == 0:
        unicode_samples = (
            "Unicode café Δ",
            "Unicode Café decomposed",
            "Unicode 😀 emoji",
            "Unicode 👩‍👩‍👧‍👦 ZWJ",
            "Unicode Greek Σ σ ς",
            "Unicode Turkish İ I ı i",
            "Unicode Straße",
            "Unicode K ſ",
            "Unicode 東京 مرحبا שלום",
            "Unicode NBSP thin space",
        )
        sample = unicode_samples[(index // 131) % len(unicode_samples)]
        title = f"{sample} synthetic {index:09d}"
    elif index % 173 == 0:
        title = f"Regex .* synthetic {index:09d}"
    elif index % 211 == 0:
        title = title.upper()

    duration: int | None
    if index % 89 == 0:
        duration = None
    elif index % 67 == 0:
        duration = 3600
    elif index % 71 == 0:
        duration = 3599
    elif index % 73 == 0:
        duration = 3601
    else:
        duration = rng.randint(0, 172_800)

    view_count = None if index % 83 == 0 else rng.randrange(0, 25_000_001)
    availability = None if index % 149 == 0 else ("private" if index % 101 == 0 else "public")
    live_status = "is_live" if index % 503 == 0 else ("was_live" if index % 257 == 0 else None)
    release_timestamp = None if index % 127 == 0 else int(release.timestamp())
    upload_date = None if index % 109 == 0 else release.strftime("%Y%m%d")

    return {
        "id": media_id,
        "title": title,
        "upload_date": upload_date,
        "release_timestamp": release_timestamp,
        "timestamp": release_timestamp,
        "duration": duration,
        "view_count": view_count,
        "like_count": None if view_count is None else rng.randint(0, 1_000_000),
        "comment_count": None if view_count is None else rng.randint(0, 100_000),
        "availability": availability,
        "live_status": live_status,
        "is_live": live_status == "is_live",
        "was_live": live_status == "was_live",
        "channel_id": f"fixture-channel-{index % 11}",
        "channel": f"Conformance Fixture {index % 11}",
        "uploader": f"Conformance Fixture {index % 11}",
        "webpage_url": f"https://fixture.invalid/watch/{media_id}",
        "fixture_group": index % 17,
        "fixture_nullable": None if index % 19 == 0 else f"g{index % 13}",
    }


def build_records(size: int, *, seed: int = DATASET_SEED) -> list[dict[str, object]]:
    """Build exactly ``size`` deterministic records for one logical source."""
    if size < 1:
        raise ValueError("dataset size must be at least 1")
    anchors = _anchor_records(seed)
    if size <= len(anchors):
        return anchors[:size]

    rows = list(anchors)
    rng = random.Random(seed ^ 0x59545351)
    # Advance through a fixed number of draws per generated row by creating records in
    # sequence. Therefore every N-record dataset is an exact prefix of every larger one
    # produced with the same generator version and seed.
    for index in range(len(anchors) + 1, size + 1):
        rows.append(_generated_record(index, rng))
    return rows


def profile_size(profile: str) -> int:
    try:
        return PROFILE_SIZES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown dataset profile: {profile}") from exc


def dataset_digest(records: Iterable[dict[str, object]]) -> str:
    """Return a stable digest of the logical record sequence."""
    digest = hashlib.sha256()
    for record in records:
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest.update(encoded.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def payload(size: int, *, seed: int = DATASET_SEED, profile: str | None = None) -> dict[str, object]:
    records = build_records(size, seed=seed)
    return {
        "kind": "yt-sql-conformance-dataset",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "profile": profile,
        "source_handle": SOURCE_HANDLE,
        "source_url": SOURCE_URL,
        "generated_at": GENERATED_AT,
        "record_count": len(records),
        "record_digest_sha256": dataset_digest(records),
        "records": records,
    }


def write_json(path: Path, *, size: int, seed: int = DATASET_SEED, profile: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload(size, seed=seed, profile=profile), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_cache(path: Path, *, size: int, seed: int = DATASET_SEED) -> None:
    if path.exists():
        path.unlink()
    records = build_records(size, seed=seed)
    fetched_at = datetime.fromisoformat(GENERATED_AT)
    with MetadataCache(path) as cache:
        cache.put_many(SOURCE_URL, records, fetched_at=fetched_at)
        ids = [str(record["id"]) for record in records]
        cache.record_source_entries(SOURCE_URL, ids, observed_at=fetched_at)
        cache.record_source_observation(SOURCE_URL, "channel", len(ids), observed_at=fetched_at)
        cache.record_source_frontier(SOURCE_URL, "channel", ids, overlap_confirmations=0, verified_at=fetched_at)
        cache.record_source_coverage(
            SOURCE_URL,
            "channel",
            len(ids),
            complete=True,
            reason="ephemeral yt-sql conformance dataset",
            observed_at=fetched_at,
        )


def _write_profile(output_dir: Path, profile: str, seed: int, *, size: int | None = None) -> None:
    resolved_size = profile_size(profile) if size is None else size
    profile_dir = output_dir / profile
    write_json(profile_dir / "dataset.json", size=resolved_size, seed=seed, profile=profile)
    write_cache(profile_dir / "metadata.sqlite3", size=resolved_size, seed=seed)


def generate_profiles(
    output_dir: Path,
    *,
    seed: int = DATASET_SEED,
    profiles: dict[str, int] | None = None,
    progress: bool = True,
) -> None:
    """Generate every supplied named profile into sibling directories."""
    selected = PROFILE_SIZES if profiles is None else profiles
    for name, size in selected.items():
        if size < 1:
            raise ValueError(f"profile {name!r} must contain at least one record")
        if progress:
            print(f"Generating {name} profile ({size:,} records)...", file=sys.stderr, flush=True)
        _write_profile(output_dir, name, seed, size=size)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate deterministic yt-sql conformance datasets.")
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument("--profile", choices=tuple(PROFILE_SIZES), help="generate one named profile")
    choice.add_argument("--size", type=int, help="generate exactly this many records")
    parser.add_argument("--seed", type=int, default=DATASET_SEED, help="deterministic generator seed")
    parser.add_argument("--json", type=Path, help="write dataset JSON for one profile/custom size")
    parser.add_argument("--cache", type=Path, help="write seeded yt-discover SQLite cache for one profile/custom size")
    parser.add_argument(
        "--output-dir", type=Path, help="write profile directories; default mode generates all profiles"
    )
    args = parser.parse_args()

    if args.size is not None and args.size < 1:
        parser.error("--size must be at least 1")

    if args.profile is None and args.size is None:
        if args.output_dir is None:
            parser.error("without --profile or --size, --output-dir is required to generate all four profiles")
        if args.json is not None or args.cache is not None:
            parser.error("--json/--cache require --profile or --size")
        generate_profiles(args.output_dir, seed=args.seed)
        return 0

    size = args.size if args.size is not None else profile_size(str(args.profile))
    profile = str(args.profile) if args.profile is not None else None
    if args.json is None and args.cache is None and args.output_dir is None:
        parser.error("specify --json, --cache or --output-dir")

    if args.output_dir is not None:
        label = profile or f"custom-{size}"
        target = args.output_dir / label
        write_json(target / "dataset.json", size=size, seed=args.seed, profile=profile)
        write_cache(target / "metadata.sqlite3", size=size, seed=args.seed)
    if args.json is not None:
        write_json(args.json, size=size, seed=args.seed, profile=profile)
    if args.cache is not None:
        write_cache(args.cache, size=size, seed=args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
