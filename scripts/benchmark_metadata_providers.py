#!/usr/bin/env python3
"""Benchmark experimental known-video metadata providers against yt-dlp."""

from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

FAILURE_PATTERNS = (
    ("private", ("private video",)),
    ("removed", ("has been removed", "removed for violating")),
    ("rate_limited", ("http error 429", "too many requests")),
    ("authentication_required", ("sign in to confirm", "authentication", "age-restricted", "age restricted")),
    ("unavailable", ("video is unavailable", "not available")),
)

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "yt_media_tools" / "youtubejs_bridge.mjs"
PROVIDERS = ("youtubejs", "youtube-innertube", "ytdlp")
COMPARISON_FIELDS = (
    "id",
    "title",
    "description",
    "channel_id",
    "duration",
    "view_count",
    "upload_date",
    "category",
    "is_live",
    "keywords",
)


def _json_lines(command: list[str]) -> tuple[list[dict[str, Any]], float, str]:
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command exited with status {result.returncode}")
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows, elapsed, result.stderr


def _normalise_youtubejs(row: dict[str, Any]) -> dict[str, Any]:
    if not row.get("ok", True):
        return _failure_row(str(row.get("id", "")), str(row.get("error", "YouTube.js acquisition failed")))
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "description": row.get("short_description"),
        "channel_id": row.get("channel_id"),
        "duration": row.get("duration"),
        "view_count": row.get("view_count"),
        "upload_date": None,
        "category": None,
        "is_live": row.get("is_live"),
        "keywords": row.get("keywords"),
        "ok": row.get("ok", True),
    }


def _normalise_youtube_innertube(video_id: str, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": video_id,
        "title": row.get("title"),
        "description": row.get("description"),
        "channel_id": row.get("channelId"),
        "duration": row.get("durationSeconds"),
        "view_count": row.get("viewCount"),
        "upload_date": row.get("publishDate"),
        "category": row.get("category"),
        "is_live": row.get("isLive"),
        "keywords": row.get("keywords"),
        "ok": True,
    }


def _normalise_ytdlp(row: dict[str, Any]) -> dict[str, Any]:
    categories = row.get("categories")
    category = categories[0] if isinstance(categories, list) and len(categories) == 1 else categories
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "channel_id": row.get("channel_id"),
        "duration": row.get("duration"),
        "view_count": row.get("view_count"),
        "upload_date": row.get("upload_date"),
        "category": category,
        "is_live": row.get("is_live"),
        "keywords": row.get("tags"),
        "ok": True,
    }


def _youtubejs(video_ids: list[str]) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js was not found in PATH")
    rows, elapsed, stderr = _json_lines([node, str(BRIDGE), "--benchmark-basic-info", *video_ids])
    return [_normalise_youtubejs(row) for row in rows], elapsed, {"stderr_bytes": len(stderr.encode("utf-8"))}


def _youtube_innertube(video_ids: list[str]) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    try:
        module = importlib.import_module("youtube_innertube")
    except ImportError as exc:
        raise RuntimeError(
            "youtube-innertube is not installed; install it from https://github.com/danielvangulla/youtube-innertube"
        ) from exc
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    started = time.perf_counter()
    for video_id in video_ids:
        item_started = time.perf_counter()
        try:
            raw = module.video_details(video_id)
            row = _normalise_youtube_innertube(video_id, raw)
            row["elapsed_ms"] = (time.perf_counter() - item_started) * 1000.0
            rows.append(row)
        except Exception as exc:  # noqa: BLE001 - benchmark must record third-party failure characteristics.
            rows.append(_failure_row(video_id, str(exc), error_type=type(exc).__name__))
            failures.append({"id": video_id, "error_type": type(exc).__name__, "kind": _classify_failure(str(exc))})
    elapsed = time.perf_counter() - started
    return rows, elapsed, {"failures": failures}


def _classify_failure(message: str) -> str:
    lowered = message.lower()
    for kind, patterns in FAILURE_PATTERNS:
        if any(pattern in lowered for pattern in patterns):
            return kind
    return "provider_error"


def _failure_row(video_id: str, message: str, *, error_type: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": video_id,
        "ok": False,
        "failure": {"kind": _classify_failure(message), "message": message},
    }
    if error_type:
        row["failure"]["error_type"] = error_type
    return row


def _ytdlp_diagnostics_by_id(stderr: str, video_ids: list[str]) -> dict[str, str]:
    messages: dict[str, list[str]] = {video_id: [] for video_id in video_ids}
    current_id: str | None = None
    id_pattern = re.compile(r"\[youtube\]\s+([^:]+):")
    for line in stderr.splitlines():
        match = id_pattern.search(line)
        if match and match.group(1) in messages:
            current_id = match.group(1)
        if current_id is not None:
            messages[current_id].append(line)
    return {video_id: "\n".join(lines).strip() for video_id, lines in messages.items() if lines}


def _ytdlp(video_ids: list[str]) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    executable = shutil.which("yt-dlp")
    if executable is None:
        raise RuntimeError("yt-dlp was not found in PATH")
    urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]
    started = time.perf_counter()
    result = subprocess.run(
        [executable, "--dump-json", "--skip-download", "--ignore-errors", *urls],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    successful_rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"yt-dlp emitted invalid JSON: {exc}") from exc
        if isinstance(value, dict):
            successful_rows.append(_normalise_ytdlp(value))
    successful = _index(successful_rows)
    per_id_diagnostics = _ytdlp_diagnostics_by_id(result.stderr, video_ids)
    rows: list[dict[str, Any]] = []
    for video_id in video_ids:
        if video_id in successful:
            rows.append(successful[video_id])
            continue
        message = per_id_diagnostics.get(video_id) or f"yt-dlp did not return metadata for {video_id}"
        rows.append(_failure_row(video_id, message))
    if result.returncode != 0 and not rows:
        raise RuntimeError(result.stderr.strip() or f"yt-dlp exited with status {result.returncode}")
    return (
        rows,
        elapsed,
        {
            "stderr_bytes": len(result.stderr.encode("utf-8")),
            "items": [
                {"id": video_id, "message": message, "kind": _classify_failure(message)}
                for video_id, message in per_id_diagnostics.items()
            ],
        },
    )


RUNNERS: dict[str, Callable[[list[str]], tuple[list[dict[str, Any]], float, dict[str, Any]]]] = {
    "youtubejs": _youtubejs,
    "youtube-innertube": _youtube_innertube,
    "ytdlp": _ytdlp,
}


def _provider_summary(rows: list[dict[str, Any]], expected_count: int) -> dict[str, Any]:
    succeeded = sum(1 for row in rows if row.get("ok", False))
    failures: dict[str, int] = {}
    for row in rows:
        if row.get("ok", False):
            continue
        kind = row.get("failure", {}).get("kind", "provider_error")
        failures[kind] = failures.get(kind, 0) + 1
    return {
        "expected": expected_count,
        "reported": len(rows),
        "succeeded": succeeded,
        "failed": len(rows) - succeeded,
        "failures_by_kind": failures,
    }


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["id"]): row for row in rows if row.get("id")}


def _agreement(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for field in COMPARISON_FIELDS:
        left = candidate.get(field)
        right = reference.get(field)
        if left is None or right is None:
            result[field] = "missing"
        elif left == right:
            result[field] = "equal"
        else:
            result[field] = "different"
    return result


def _numeric_delta(candidate: dict[str, Any], reference: dict[str, Any], field: str) -> dict[str, Any] | None:
    left = candidate.get(field)
    right = reference.get(field)
    if (
        isinstance(left, bool)
        or isinstance(right, bool)
        or not isinstance(left, (int, float))
        or not isinstance(right, (int, float))
    ):
        return None
    absolute = left - right
    relative_percent = None if right == 0 else (absolute / right) * 100.0
    return {"candidate": left, "reference": right, "absolute": absolute, "relative_percent": relative_percent}


def _comparison(video_id: str, candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    candidate_ok = bool(candidate.get("ok", bool(candidate)))
    reference_ok = bool(reference.get("ok", bool(reference)))
    if not candidate_ok or not reference_ok:
        if not candidate_ok and not reference_ok:
            status = "both_failed"
        elif not candidate_ok:
            status = "candidate_failed"
        else:
            status = "reference_failed"
        return {
            "id": video_id,
            "ok": False,
            "status": status,
            "candidate_failure": candidate.get("failure"),
            "reference_failure": reference.get("failure"),
            "agreement": {},
            "deltas": {},
        }
    agreement = _agreement(candidate, reference)
    deltas: dict[str, dict[str, Any]] = {}
    if agreement["view_count"] == "different":
        view_count_delta = _numeric_delta(candidate, reference, "view_count")
        if view_count_delta is not None:
            deltas["view_count"] = view_count_delta
    return {"id": video_id, "ok": True, "status": "compared", "agreement": agreement, "deltas": deltas}


def _provider_names(value: str) -> list[str]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [name for name in names if name not in PROVIDERS]
    if invalid:
        raise argparse.ArgumentTypeError(f"unknown provider(s): {', '.join(invalid)}")
    if "ytdlp" not in names:
        names.append("ytdlp")
    return names


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="+", help="YouTube video IDs forming the benchmark corpus")
    parser.add_argument(
        "--providers",
        type=_provider_names,
        default=list(PROVIDERS),
        help="comma-separated providers (youtubejs,youtube-innertube,ytdlp); ytdlp is always included as the reference",
    )
    parser.add_argument("--json", action="store_true", help="emit the complete machine-readable benchmark result")
    args = parser.parse_args()

    provider_results: dict[str, dict[str, Any]] = {}
    for name in args.providers:
        rows, elapsed, diagnostics = RUNNERS[name](args.video_id)
        provider_results[name] = {
            "elapsed_seconds": elapsed,
            "rows": rows,
            "diagnostics": diagnostics,
            "summary": _provider_summary(rows, len(args.video_id)),
        }

    reference = _index(provider_results["ytdlp"]["rows"])
    comparisons: dict[str, list[dict[str, Any]]] = {}
    for name in args.providers:
        if name == "ytdlp":
            continue
        candidate = _index(provider_results[name]["rows"])
        comparisons[name] = [
            _comparison(video_id, candidate.get(video_id, {}), reference.get(video_id, {}))
            for video_id in args.video_id
        ]

    payload = {
        "schema_version": 3,
        "corpus_size": len(args.video_id),
        "providers": provider_results,
        "comparisons": comparisons,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Corpus: {len(args.video_id)} videos")
        for name in args.providers:
            print(f"{name}: {provider_results[name]['elapsed_seconds']:.3f}s")
        for name, items in comparisons.items():
            print(f"\n{name} against yt-dlp:")
            for item in items:
                summary = ", ".join(f"{field}={state}" for field, state in item["agreement"].items())
                print(f"{item['id']}: {summary}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
