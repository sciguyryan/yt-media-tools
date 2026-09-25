#!/usr/bin/env python3
"""Acquire metadata-provider observations and assess them against browser page-source evidence."""

from __future__ import annotations

import argparse
import hashlib
import html as html_module
import importlib.util
import json
import re
import subprocess
import sys
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_SCRIPT = ROOT / "scripts" / "benchmark_metadata_providers.py"
DEFAULT_CORPUS = ROOT / "benchmarks" / "metadata-provider-corpora" / "issue-114-human-authority.json"
DEFAULT_OUTPUT = ROOT / ".benchmarks" / "issue-114-authority-evidence.json"
DEFAULT_PROVIDERS = ("youtubejs", "ytdlp")
DEFAULT_SOURCE_DIRECTORY = ROOT / ".benchmarks" / "page-source-inbox"
SOURCE_END_MARKER = "<<<END-SOURCE>>>"
MAX_SOURCE_BYTES = 32 * 1024 * 1024
SOURCE_POLL_SECONDS = 0.25
SOURCE_STABLE_POLLS = 5
SOURCE_PARSE_RETRIES = 3
ASSESSMENT_FIELDS = (
    "title",
    "description",
    "channel_id",
    "duration",
    "view_count",
    "keywords",
    "is_live",
    "publish_date",
    "upload_date",
    "start_timestamp",
    "is_live_content",
    "is_private",
    "is_unlisted",
)
JUDGEMENTS = ("exact", "approximate", "incorrect", "different-semantic", "ambiguous", "unverifiable")

# Explicit first-party paths only. Finding an identically named property elsewhere is not evidence for a field.
PLAYER_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "video_id": (("videoDetails", "videoId"), ("microformat", "playerMicroformatRenderer", "externalVideoId")),
    "title": (("videoDetails", "title"), ("microformat", "playerMicroformatRenderer", "title", "simpleText")),
    "description": (
        ("videoDetails", "shortDescription"),
        ("microformat", "playerMicroformatRenderer", "description", "simpleText"),
    ),
    "channel_id": (("videoDetails", "channelId"), ("microformat", "playerMicroformatRenderer", "externalChannelId")),
    "duration": (("videoDetails", "lengthSeconds"), ("microformat", "playerMicroformatRenderer", "lengthSeconds")),
    "view_count": (("videoDetails", "viewCount"), ("microformat", "playerMicroformatRenderer", "viewCount")),
    "keywords": (("videoDetails", "keywords"),),
    "is_live_content": (("videoDetails", "isLiveContent"),),
    "is_private": (("videoDetails", "isPrivate"),),
    "is_unlisted": (("microformat", "playerMicroformatRenderer", "isUnlisted"),),
    "publish_date": (("microformat", "playerMicroformatRenderer", "publishDate"),),
    "upload_date": (("microformat", "playerMicroformatRenderer", "uploadDate"),),
    "start_timestamp": (("microformat", "playerMicroformatRenderer", "liveBroadcastDetails", "startTimestamp"),),
    "channel_name": (("videoDetails", "author"), ("microformat", "playerMicroformatRenderer", "ownerChannelName")),
    "category": (("microformat", "playerMicroformatRenderer", "category"),),
    "thumbnails": (("videoDetails", "thumbnail", "thumbnails"),),
}

INITIAL_DATA_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "channel_id": (
        (
            "contents",
            "twoColumnWatchNextResults",
            "results",
            "results",
            "contents",
            "*",
            "videoSecondaryInfoRenderer",
            "owner",
            "videoOwnerRenderer",
            "navigationEndpoint",
            "browseEndpoint",
            "browseId",
        ),
        (
            "contents",
            "twoColumnWatchNextResults",
            "results",
            "results",
            "contents",
            "*",
            "videoSecondaryInfoRenderer",
            "subscribeButton",
            "subscribeButtonRenderer",
            "subscribeEndpoint",
            "channelIds",
            "0",
        ),
    ),
}

META_FIELDS = {
    "videoId": "video_id",
    "channelId": "channel_id",
    "name": "title",
    "description": "description",
    "duration": "duration_iso8601",
    "datePublished": "publish_date",
    "uploadDate": "upload_date",
    "interactionCount": "view_count",
}


def _load_benchmark_module():
    spec = importlib.util.spec_from_file_location("metadata_provider_benchmark", BENCHMARK_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load metadata-provider benchmark module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_corpus(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("assessment corpus must contain a non-empty items array")
    result = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("every corpus item must contain a string id")
        result.append({"id": item["id"], "traits": list(item.get("traits", []))})
    return result


def _provider_value(row: dict[str, Any], field: str) -> Any:
    if field in row and row.get(field) is not None:
        return row.get(field)
    signals = row.get("source_signals")
    return signals.get(field) if isinstance(signals, dict) else None


def _neutral_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return sorted(value, key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
    return value


def _blind_order(assessment_id: str, video_id: str, field: str, providers: list[str]) -> list[str]:
    def key(provider: str) -> bytes:
        return hashlib.sha256(f"{assessment_id}\0{video_id}\0{field}\0{provider}".encode()).digest()

    return sorted(providers, key=key)


def _blind_candidates(
    assessment_id: str, video_id: str, field: str, rows: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    providers = _blind_order(assessment_id, video_id, field, list(rows))
    return [
        {
            "candidate": chr(ord("A") + index),
            "value": _neutral_value(_provider_value(rows[provider], field)),
            "provider": provider,
        }
        for index, provider in enumerate(providers)
    ]


def _public_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"candidate": item["candidate"], "value": item["value"]} for item in candidates]


def _acquire(corpus: list[dict[str, Any]], providers: list[str]) -> dict[str, Any]:
    benchmark = _load_benchmark_module()
    video_ids = [item["id"] for item in corpus]
    observations: dict[str, Any] = {}
    for provider in providers:
        rows, elapsed, diagnostics = benchmark._run_provider(provider, video_ids, "core")
        observations[provider] = {"elapsed_seconds": elapsed, "diagnostics": diagnostics, "rows": rows}
    return observations


def _prepare(corpus_path: Path, output: Path, providers: list[str]) -> None:
    corpus = _load_corpus(corpus_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "assessment_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus,
        "providers": providers,
        "observations": _acquire(corpus, providers),
        "page_source_evidence": [],
        "assessments": [],
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Prepared blind assessment: {output}")
    print("Provider provenance is stored in the evidence file but is not shown before review is required.")


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.values: list[tuple[str, str]] = []
        self.canonical_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "meta":
            key = data.get("itemprop") or data.get("property") or data.get("name")
            value = data.get("content")
            if key and value:
                self.values.append((key, value))
        elif tag.lower() == "link" and data.get("rel", "").lower() == "canonical" and data.get("href"):
            self.canonical_urls.append(data["href"])


def _assigned_json_diagnostics(source: str, variable: str) -> tuple[list[Any], int, int]:
    results: list[Any] = []
    assignments = 0
    decode_failures = 0
    for match in re.finditer(rf"(?:var\s+)?{re.escape(variable)}\s*=\s*", source):
        assignments += 1
        start = match.end()
        while start < len(source) and source[start].isspace():
            start += 1
        if start >= len(source) or source[start] not in "[{":
            decode_failures += 1
            continue
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(source[start:])
        except json.JSONDecodeError:
            decode_failures += 1
            continue
        results.append(value)
    return results, assignments, decode_failures


def _extract_assigned_json(source: str, variable: str) -> list[Any]:
    return _assigned_json_diagnostics(source, variable)[0]


def _walk_path(value: Any, path: tuple[str, ...]) -> list[Any]:
    if not path:
        return [value]
    head, *tail = path
    if head == "*":
        if not isinstance(value, list):
            return []
        return [result for item in value for result in _walk_path(item, tuple(tail))]
    if isinstance(value, list) and head.isdigit():
        index = int(head)
        return _walk_path(value[index], tuple(tail)) if index < len(value) else []
    if not isinstance(value, dict) or head not in value:
        return []
    return _walk_path(value[head], tuple(tail))


def _record(evidence: dict[str, list[dict[str, Any]]], field: str, value: Any, source: str, path: str) -> None:
    if value is None:
        return
    item = {"value": value, "source": source, "path": path}
    if item not in evidence.setdefault(field, []):
        evidence[field].append(item)


def _extract_first_party_evidence(source: str, expected_video_id: str) -> dict[str, Any]:
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SOURCE_BYTES:
        raise ValueError(f"page source exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MiB safety limit")
    evidence: dict[str, list[dict[str, Any]]] = {}
    structures: list[str] = []
    structure_diagnostics: dict[str, dict[str, int]] = {}
    for root_name, path_map in (("ytInitialPlayerResponse", PLAYER_PATHS), ("ytInitialData", INITIAL_DATA_PATHS)):
        objects, assignments, decode_failures = _assigned_json_diagnostics(source, root_name)
        structure_diagnostics[root_name] = {
            "text_occurrences": source.count(root_name),
            "assignments": assignments,
            "decoded": len(objects),
            "decode_failures": decode_failures,
        }
        if objects:
            structures.append(root_name)
        for obj in objects:
            for field, paths in path_map.items():
                for path in paths:
                    for value in _walk_path(obj, path):
                        _record(evidence, field, value, root_name, ".".join(path))
    parser = _MetaParser()
    parser.feed(source)
    for key, value in parser.values:
        if key in META_FIELDS:
            _record(evidence, META_FIELDS[key], html_module.unescape(value), "html-meta", key)
    for url in parser.canonical_urls:
        match = re.search(r"[?&]v=([A-Za-z0-9_-]{11})(?:&|$)", url)
        if match:
            _record(evidence, "video_id", match.group(1), "canonical-link", "href")
    ids = {str(item["value"]) for item in evidence.get("video_id", [])}
    if not structures and not evidence:
        summary = "; ".join(
            f"{name}: occurrences={stats['text_occurrences']}, assignments={stats['assignments']}, decoded={stats['decoded']}, decode_failures={stats['decode_failures']}"
            for name, stats in structure_diagnostics.items()
        )
        raise ValueError(
            f"input does not contain recognised YouTube page-source evidence ({summary}; expected_video_id_occurrences={source.count(expected_video_id)})"
        )
    if not ids:
        raise ValueError("could not establish the video ID from recognised first-party page-source paths")
    if expected_video_id not in ids:
        raise ValueError(f"page source identifies video(s) {', '.join(sorted(ids))}, expected {expected_video_id}")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_length": len(encoded),
        "recognised_structures": sorted(structures),
        "structure_diagnostics": structure_diagnostics,
        "fields": evidence,
    }


def _comparison_value(field: str, value: Any) -> Any:
    value = _neutral_value(value)
    if field in {"duration", "view_count"}:
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if field in {"publish_date", "upload_date"} and isinstance(value, str):
        return value.replace("-", "")
    return value


def _source_matches(field: str, candidate: Any, page_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    target = _comparison_value(field, candidate)
    return [
        item
        for item in page_evidence.get("fields", {}).get(field, [])
        if _comparison_value(field, item.get("value")) == target
    ]


def _read_pasted_source() -> str:
    print("Paste the complete View Source contents below.")
    print(f"When finished, enter {SOURCE_END_MARKER} on a new line.")
    chunks: list[str] = []
    total = 0
    while True:
        line = input()
        if line == SOURCE_END_MARKER:
            break
        total += len(line.encode("utf-8")) + 1
        if total > MAX_SOURCE_BYTES:
            raise ValueError(f"page source exceeds {MAX_SOURCE_BYTES // (1024 * 1024)} MiB safety limit")
        chunks.append(line)
    return "\n".join(chunks)


def _source_directory_snapshot(directory: Path) -> dict[Path, tuple[int, int]]:
    result: dict[Path, tuple[int, int]] = {}
    if not directory.exists():
        return result
    for item in directory.iterdir():
        if item.is_file():
            stat = item.stat()
            result[item] = (stat.st_mtime_ns, stat.st_size)
    return result


def _wait_for_saved_source(
    directory: Path, before: dict[Path, tuple[int, int]], expected_video_id: str
) -> tuple[str, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Save the complete View Source into: {directory.resolve()}")
    print("Waiting for a new or changed source file. Press Ctrl-C to cancel.")
    seen_candidate: tuple[Path, tuple[int, int]] | None = None
    stable_polls = 0
    last_parse_error: ValueError | None = None
    parse_failures = 0
    while True:
        current = _source_directory_snapshot(directory)
        changed = [
            (path, state)
            for path, state in current.items()
            if before.get(path) != state and 0 < state[1] <= MAX_SOURCE_BYTES
        ]
        changed.sort(key=lambda item: (item[1][0], item[0].name), reverse=True)
        if changed:
            candidate = changed[0]
            if seen_candidate == candidate:
                stable_polls += 1
            else:
                seen_candidate = candidate
                stable_polls = 1
                last_parse_error = None
                parse_failures = 0
            if stable_polls >= SOURCE_STABLE_POLLS:
                try:
                    source = candidate[0].read_text(encoding="utf-8")
                    _extract_first_party_evidence(source, expected_video_id)
                except (OSError, UnicodeError, ValueError) as exc:
                    # A browser may pause while writing a large View Source file. Keep watching
                    # rather than treating a transient partial file as final evidence.
                    if isinstance(exc, ValueError):
                        last_parse_error = exc
                    parse_failures += 1
                    if parse_failures >= SOURCE_PARSE_RETRIES:
                        if last_parse_error is not None:
                            raise last_parse_error
                        raise ValueError(f"could not read stable saved source file {candidate[0]}") from exc
                    stable_polls = 0
                else:
                    return source, candidate[0]
        else:
            seen_candidate = None
            stable_polls = 0
            last_parse_error = None
            parse_failures = 0
        time.sleep(SOURCE_POLL_SECONDS)


def _prompt(prompt: str, allowed: tuple[str, ...] | None = None) -> str:
    while True:
        value = input(prompt).strip()
        if allowed is None or value in allowed:
            return value
        print(f"Expected one of: {', '.join(allowed)}")


def _record_page_source(payload: dict[str, Any], video_id: str, source: str) -> dict[str, Any]:
    parsed = _extract_first_party_evidence(source, video_id)
    record = {"id": video_id, "captured_at": datetime.now(timezone.utc).isoformat(), **parsed}
    existing = payload.setdefault("page_source_evidence", [])
    existing[:] = [item for item in existing if item.get("id") != video_id]
    existing.append(record)
    return record


def _assess(
    path: Path,
    *,
    open_browser: bool,
    source_file: Path | None = None,
    source_directory: Path | None = None,
    paste_source: bool = False,
) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assessment_id = str(payload["assessment_id"])
    providers = list(payload["providers"])
    observations = payload["observations"]
    by_provider = {
        provider: {str(row.get("id")): row for row in observations[provider]["rows"] if row.get("id")}
        for provider in providers
    }
    page_by_id = {item["id"]: item for item in payload.get("page_source_evidence", [])}
    completed = {(item["id"], item["field"]) for item in payload.get("assessments", [])}
    corpus = payload["corpus"]
    if source_file is not None and len(corpus) != 1:
        raise ValueError("--source-file is supported only when the assessment corpus contains one video")
    for corpus_item in corpus:
        video_id = corpus_item["id"]
        url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"\nVideo {video_id} | traits: {', '.join(corpus_item.get('traits', []))}")
        print(f"First-party page: {url}")
        watch_snapshot: dict[Path, tuple[int, int]] | None = None
        if source_directory is not None:
            source_directory.mkdir(parents=True, exist_ok=True)
            watch_snapshot = _source_directory_snapshot(source_directory)
        if open_browser:
            webbrowser.open(url, new=2)
        page = page_by_id.get(video_id)
        if page is None:
            consumed_path: Path | None = None
            if source_file is not None:
                source = source_file.read_text(encoding="utf-8")
            elif paste_source:
                source = _read_pasted_source()
            else:
                assert source_directory is not None and watch_snapshot is not None
                source, consumed_path = _wait_for_saved_source(source_directory, watch_snapshot, video_id)
            page = _record_page_source(payload, video_id, source)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            page_by_id[video_id] = page
            print(
                f"Parsed {len(page['fields'])} first-party evidence fields; raw page source discarded by the assessor."
            )
            if consumed_path is not None:
                try:
                    consumed_path.unlink()
                except OSError as exc:
                    print(f"Warning: could not delete consumed source file {consumed_path}: {exc}", file=sys.stderr)
                else:
                    print(f"Deleted consumed source file: {consumed_path}")
        rows = {provider: by_provider[provider].get(video_id, {}) for provider in providers}
        for field in ASSESSMENT_FIELDS:
            if (video_id, field) in completed:
                continue
            blind = _blind_candidates(assessment_id, video_id, field, rows)
            public = _public_candidates(blind)
            if all(item["value"] is None for item in public):
                continue
            source_values = page.get("fields", {}).get(field, [])
            matches = {
                item["candidate"]: _source_matches(field, item["value"], page)
                for item in public
                if item["value"] is not None
            }
            unique_provider_values = {json.dumps(item["value"], ensure_ascii=False, sort_keys=True) for item in public}
            requires_review = len(unique_provider_values) > 1 or not all(
                matches.get(item["candidate"]) for item in public if item["value"] is not None
            )
            record: dict[str, Any] = {
                "id": video_id,
                "field": field,
                "blind_candidates": public,
                "first_party_evidence": source_values,
                "automatic_corroboration": [
                    {"candidate": key, "evidence": value} for key, value in matches.items() if value
                ],
                "provenance_reveal": [{"candidate": item["candidate"], "provider": item["provider"]} for item in blind],
                "assessed_at": datetime.now(timezone.utc).isoformat(),
            }
            if requires_review:
                print(f"\nField requiring review: {field}")
                for evidence_item in source_values:
                    print(
                        f"  First-party [{evidence_item['source']}:{evidence_item['path']}]: {json.dumps(evidence_item['value'], ensure_ascii=False)}"
                    )
                for item in public:
                    print(f"  Candidate {item['candidate']}: {json.dumps(item['value'], ensure_ascii=False)}")
                judgements = []
                for item in public:
                    judgement = _prompt(
                        f"Candidate {item['candidate']} judgement ({'/'.join(JUDGEMENTS)}): ", JUDGEMENTS
                    )
                    judgements.append({"candidate": item["candidate"], "judgement": judgement})
                record["candidate_judgements"] = judgements
                notes = _prompt("Evidence/semantic notes (optional): ")
                record["notes"] = notes or None
                record["review"] = "human"
                print("Recorded. Provenance:")
                for item in record["provenance_reveal"]:
                    print(f"  Candidate {item['candidate']}: {item['provider']}")
            else:
                record["review"] = "automatically-corroborated"
                print(f"  {field}: provider values corroborated by recognised first-party source paths")
            payload.setdefault("assessments", []).append(record)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Assessment complete: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="acquire provider observations and create an assessment evidence file")
    prepare.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    prepare.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    prepare.add_argument("--providers", nargs="+", default=list(DEFAULT_PROVIDERS))
    assess = sub.add_parser("assess", help="parse browser page source and review only unresolved metadata evidence")
    assess.add_argument("evidence", type=Path, nargs="?", default=DEFAULT_OUTPUT)
    assess.add_argument(
        "--open-browser", action="store_true", help="open each canonical watch page in the default browser"
    )
    source_group = assess.add_mutually_exclusive_group()
    source_group.add_argument("--source-file", type=Path, help="read page source from a file for a single-video corpus")
    source_group.add_argument(
        "--source-directory",
        type=Path,
        default=DEFAULT_SOURCE_DIRECTORY,
        help="watch this directory for saved View Source files (default: .benchmarks/page-source-inbox)",
    )
    source_group.add_argument(
        "--paste-source",
        action="store_true",
        help="paste View Source interactively and finish with the explicit end marker",
    )
    args = parser.parse_args()
    if args.command == "prepare":
        _prepare(args.corpus, args.output, args.providers)
    else:
        _assess(
            args.evidence,
            open_browser=args.open_browser,
            source_file=args.source_file,
            source_directory=None if args.source_file or args.paste_source else args.source_directory,
            paste_source=args.paste_source,
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"assessment error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
