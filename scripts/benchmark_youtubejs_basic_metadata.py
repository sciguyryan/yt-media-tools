#!/usr/bin/env python3
"""Compare YouTube.js basic metadata acquisition with yt-dlp detailed extraction."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "yt_media_tools" / "youtubejs_bridge.mjs"
COMPARISON_FIELDS = ("id", "title", "channel_id", "duration", "view_count")


def _json_lines(command: list[str]) -> tuple[list[dict[str, Any]], float, str]:
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed = time.perf_counter() - started
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"command exited with status {result.returncode}")
    rows = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows, elapsed, result.stderr


def _youtubejs(video_ids: list[str]) -> tuple[list[dict[str, Any]], float]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js was not found in PATH")
    rows, elapsed, _ = _json_lines([node, str(BRIDGE), "--benchmark-basic-info", *video_ids])
    return rows, elapsed


def _ytdlp(video_ids: list[str]) -> tuple[list[dict[str, Any]], float]:
    executable = shutil.which("yt-dlp")
    if executable is None:
        raise RuntimeError("yt-dlp was not found in PATH")
    urls = [f"https://www.youtube.com/watch?v={video_id}" for video_id in video_ids]
    rows, elapsed, _ = _json_lines([executable, "--dump-json", "--skip-download", *urls])
    return rows, elapsed


def _index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in rows if row.get("id")}


def _agreement(youtubejs: dict[str, Any], ytdlp: dict[str, Any]) -> dict[str, str]:
    result = {}
    for field in COMPARISON_FIELDS:
        left = youtubejs.get(field)
        right = ytdlp.get(field)
        if left is None or right is None:
            result[field] = "missing"
        elif left == right:
            result[field] = "equal"
        else:
            result[field] = "different"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="+", help="YouTube video IDs forming the benchmark corpus")
    parser.add_argument("--json", action="store_true", help="emit the complete machine-readable benchmark result")
    args = parser.parse_args()

    youtubejs_rows, youtubejs_elapsed = _youtubejs(args.video_id)
    ytdlp_rows, ytdlp_elapsed = _ytdlp(args.video_id)
    youtubejs_by_id = _index(youtubejs_rows)
    ytdlp_by_id = _index(ytdlp_rows)
    comparisons = []
    for video_id in args.video_id:
        comparisons.append(
            {
                "id": video_id,
                "youtubejs_ok": bool(youtubejs_by_id.get(video_id, {}).get("ok", False)),
                "agreement": _agreement(youtubejs_by_id.get(video_id, {}), ytdlp_by_id.get(video_id, {})),
            }
        )
    payload = {
        "schema_version": 1,
        "corpus_size": len(args.video_id),
        "youtubejs_elapsed_seconds": youtubejs_elapsed,
        "ytdlp_elapsed_seconds": ytdlp_elapsed,
        "comparisons": comparisons,
        "youtubejs": youtubejs_rows,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Corpus: {len(args.video_id)} videos")
        print(f"YouTube.js getBasicInfo(): {youtubejs_elapsed:.3f}s")
        print(f"yt-dlp detailed: {ytdlp_elapsed:.3f}s")
        for item in comparisons:
            summary = ", ".join(f"{field}={state}" for field, state in item["agreement"].items())
            print(f"{item['id']}: {summary}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
