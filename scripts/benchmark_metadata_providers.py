#!/usr/bin/env python3
"""Benchmark experimental known-video metadata providers against yt-dlp."""

from __future__ import annotations

import argparse
import html
import importlib
from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_cookies = importlib.import_module("yt_media_tools.cookies")
CookieFileError = _cookies.CookieFileError
cookie_header_from_netscape_file = _cookies.cookie_header_from_netscape_file
_external = importlib.import_module("yt_media_tools.external_tools")
ToolInvocation = _external.ToolInvocation
configure_external_diagnostics = _external.configure_external_diagnostics
emit_invocation = _external.emit_invocation

FAILURE_PATTERNS = (
    ("private", ("private video",)),
    ("removed", ("has been removed", "removed for violating")),
    ("rate_limited", ("http error 429", "too many requests")),
    ("authentication_required", ("sign in to confirm", "authentication", "age-restricted", "age restricted")),
    ("unavailable", ("video is unavailable", "not available")),
)

BRIDGE = ROOT / "yt_media_tools" / "youtubejs_bridge.mjs"
PROVIDERS = ("youtubejs", "youtube-innertube", "pytubefix", "newpipe-extractor", "invidious", "piped", "ytdlp")
DEFAULT_PROVIDERS = tuple(name for name in PROVIDERS if name not in {"invidious", "piped"})
MEASUREMENT_PROFILES = ("core", "full")
PROFILE_SUPPORT = {
    "youtubejs": {"core"},
    "youtube-innertube": {"core"},
    "pytubefix": {"core", "full"},
    "newpipe-extractor": {"core"},
    "invidious": {"core"},
    "piped": {"core"},
    "ytdlp": {"core", "full"},
}
YOUTUBEJS_COOKIE_ENV = "YT_DISCOVER_YOUTUBEJS_COOKIE"
NEWPIPE_BRIDGE_ENV = "YT_DISCOVER_NEWPIPE_BRIDGE"
NEWPIPE_DIAGNOSTICS_ENV = "YT_DISCOVER_NEWPIPE_DIAGNOSTICS"
INVIDIOUS_INSTANCE_ENV = "YT_DISCOVER_INVIDIOUS_INSTANCE"
INVIDIOUS_PREFLIGHT_TIMEOUT_SECONDS = 5
INVIDIOUS_REQUEST_TIMEOUT_SECONDS = 15
PIPED_INSTANCE_ENV = "YT_DISCOVER_PIPED_INSTANCE"
PIPED_PREFLIGHT_TIMEOUT_SECONDS = 5
PIPED_REQUEST_TIMEOUT_SECONDS = 15
PIPED_ERROR_DETAIL_MAX_CHARS = 500
NEWPIPE_DEFAULT_BRIDGE = (
    ROOT
    / "tools"
    / "newpipe-extractor-bridge"
    / "build"
    / "install"
    / "yt-media-tools-newpipe-bridge"
    / "bin"
    / "yt-media-tools-newpipe-bridge"
)
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


def _json_lines(command: list[str], *, env: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], float, str]:
    started = time.perf_counter()
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, env=env
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
        "source_signals": {
            "is_live": row.get("is_live"),
            "is_live_content": row.get("is_live_content"),
            "is_private": row.get("is_private"),
            "is_unlisted": row.get("is_unlisted"),
            "playability_status": row.get("playability_status"),
        },
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
        "source_signals": {
            "isLive": row.get("isLive"),
            "available_keys": sorted(str(key) for key in row),
        },
    }


def _normalise_ytdlp(row: dict[str, Any], *, include_extended: bool = False) -> dict[str, Any]:
    categories = row.get("categories")
    category = categories[0] if isinstance(categories, list) and len(categories) == 1 else categories
    extended = {"status": "not_requested"}
    if include_extended:
        thumbnails = row.get("thumbnails")
        chapters = row.get("chapters")
        subtitles = row.get("subtitles")
        automatic_captions = row.get("automatic_captions")
        caption_codes = set()
        if isinstance(subtitles, dict):
            caption_codes.update(str(code) for code in subtitles)
        if isinstance(automatic_captions, dict):
            caption_codes.update(str(code) for code in automatic_captions)
        extended = {
            "thumbnail_url": {"available": bool(thumbnails)},
            "chapters": {
                "available": chapters is not None,
                "count": len(chapters) if isinstance(chapters, list) else 0,
            },
            "captions": {"available": bool(caption_codes), "count": len(caption_codes), "codes": sorted(caption_codes)},
        }
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
        "source_signals": {
            "is_live": row.get("is_live"),
            "was_live": row.get("was_live"),
            "live_status": row.get("live_status"),
            "availability": row.get("availability"),
        },
        "extended_capabilities": extended,
    }


def _youtubejs(
    video_ids: list[str], *, cookie: str | None = None, secret_values: tuple[str, ...] = ()
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js was not found in PATH")
    env = os.environ.copy()
    if cookie is None:
        env.pop(YOUTUBEJS_COOKIE_ENV, None)
    else:
        env[YOUTUBEJS_COOKIE_ENV] = cookie
    try:
        rows, elapsed, stderr = _json_lines([node, str(BRIDGE), "--benchmark-basic-info", *video_ids], env=env)
    except RuntimeError as exc:
        raise RuntimeError(_redact_secrets(str(exc), (cookie, *secret_values))) from exc
    rows = _redact_secrets(rows, (cookie, *secret_values))
    stderr = _redact_secrets(stderr, (cookie, *secret_values))
    return (
        [_normalise_youtubejs(row) for row in rows],
        elapsed,
        {
            "stderr_bytes": len(stderr.encode("utf-8")),
            "authentication": "cookie" if cookie is not None else "anonymous",
        },
    )


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


def _normalise_pytubefix(video_id: str, video: Any, *, include_extended: bool = False) -> dict[str, Any]:
    """Normalise pytubefix evidence without granting extended fields authority."""
    publish_date = video.publish_date
    if publish_date is None:
        upload_date = None
    elif hasattr(publish_date, "strftime"):
        upload_date = publish_date.strftime("%Y%m%d")
    else:
        upload_date = str(publish_date)

    vid_info = video.vid_info if isinstance(video.vid_info, dict) else {}
    video_details = vid_info.get("videoDetails") if isinstance(vid_info.get("videoDetails"), dict) else {}
    playability = vid_info.get("playabilityStatus") if isinstance(vid_info.get("playabilityStatus"), dict) else {}

    extended: dict[str, Any] = {}
    if include_extended:
        for name, getter in (
            ("thumbnail_url", lambda: video.thumbnail_url),
            ("chapters", lambda: video.chapters),
            ("captions", lambda: video.captions),
        ):
            try:
                value = getter()
                if name == "thumbnail_url":
                    extended[name] = {"available": bool(value)}
                elif name == "chapters":
                    extended[name] = {"available": value is not None, "count": len(value) if value is not None else 0}
                else:
                    keys = []
                    if value is not None:
                        try:
                            keys = sorted(str(key) for key in value)
                        except TypeError:
                            keys = []
                    extended[name] = {"available": bool(keys), "count": len(keys), "codes": keys}
            except Exception as exc:  # noqa: BLE001 - capability probing must not discard otherwise valid metadata.
                extended[name] = {"available": False, "error_type": type(exc).__name__}

    return {
        "id": video_id,
        "title": video.title,
        "description": video.description,
        "channel_id": video.channel_id,
        "duration": video.length,
        "view_count": video.views,
        "upload_date": upload_date,
        "category": None,
        "is_live": None,
        "keywords": video.keywords,
        "ok": True,
        "source_signals": {
            "playability_status": playability.get("status"),
            "playability_reason": playability.get("reason"),
            "is_private": video_details.get("isPrivate"),
            "is_live_content": video_details.get("isLiveContent"),
            "available_video_detail_keys": sorted(str(key) for key in video_details),
        },
        "extended_capabilities": extended if include_extended else {"status": "not_requested"},
    }


def _pytubefix(video_ids: list[str], *, profile: str = "core") -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    try:
        module = importlib.import_module("pytubefix")
    except ImportError as exc:
        raise RuntimeError("pytubefix is not installed; install it with python -m pip install pytubefix") from exc

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    started = time.perf_counter()
    for video_id in video_ids:
        item_started = time.perf_counter()
        try:
            video = module.YouTube(f"https://www.youtube.com/watch?v={video_id}")
            row = _normalise_pytubefix(video_id, video, include_extended=profile == "full")
            row["elapsed_ms"] = (time.perf_counter() - item_started) * 1000.0
            rows.append(row)
        except Exception as exc:  # noqa: BLE001 - benchmark records third-party failure characteristics.
            message = str(exc)
            rows.append(_failure_row(video_id, message, error_type=type(exc).__name__))
            failures.append({"id": video_id, "error_type": type(exc).__name__, "kind": _classify_failure(message)})
    elapsed = time.perf_counter() - started
    version = getattr(module, "__version__", None)
    return (
        rows,
        elapsed,
        {
            "failures": failures,
            "version": str(version) if version is not None else None,
            "authentication": "anonymous",
            "network_measurement": "not instrumented",
            "measurement_profile": profile,
        },
    )


def _normalise_newpipe(row: dict[str, Any]) -> dict[str, Any]:
    """Normalise NewPipeExtractor evidence without treating bridge-only signals as yt-sql authority."""
    if not row.get("ok", True):
        return _failure_row(
            str(row.get("id", "")),
            str(row.get("error", "NewPipeExtractor acquisition failed")),
            error_type=str(row.get("error_type")) if row.get("error_type") else None,
        )
    uploader_url = str(row.get("uploader_url") or "")
    channel_match = re.search(r"/channel/([^/?#]+)", uploader_url)
    stream_type = str(row.get("stream_type") or "")
    upload_date = row.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) >= 10:
        upload_date = upload_date[:10].replace("-", "")
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "description": row.get("description"),
        "channel_id": channel_match.group(1) if channel_match else None,
        "duration": row.get("duration"),
        "view_count": row.get("view_count"),
        "upload_date": upload_date,
        "category": row.get("category"),
        "is_live": "LIVE" in stream_type.upper(),
        "keywords": row.get("keywords"),
        "ok": True,
        "elapsed_ms": row.get("elapsed_ms"),
        "source_signals": {
            "uploader_name": row.get("uploader_name"),
            "uploader_url": row.get("uploader_url"),
            "upload_date_approximate": row.get("upload_date_approximate"),
            "stream_type": row.get("stream_type"),
            "content_availability": row.get("content_availability"),
            "uploader_verified": row.get("uploader_verified"),
            "short_form": row.get("short_form"),
        },
    }


def _newpipe_bridge_path() -> Path:
    configured = os.environ.get(NEWPIPE_BRIDGE_ENV)
    return Path(configured).expanduser() if configured else NEWPIPE_DEFAULT_BRIDGE


def _newpipe_extractor(video_ids: list[str]) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    bridge = _newpipe_bridge_path()
    if not bridge.is_file():
        raise RuntimeError(
            "NewPipeExtractor benchmark bridge was not found; run "
            "'gradle installDist' in tools/newpipe-extractor-bridge or set " + NEWPIPE_BRIDGE_ENV
        )
    command = [str(bridge), *video_ids]
    emit_invocation(
        ToolInvocation(
            tool="newpipe-extractor",
            operation="StreamInfo.getInfo",
            purpose="known-video metadata benchmark",
            status="executing",
            argv=tuple(command),
            arguments={"video_ids": list(video_ids)},
        )
    )
    rows, elapsed, stderr = _json_lines(command)
    if stderr and os.environ.get(NEWPIPE_DIAGNOSTICS_ENV):
        sys.stderr.write("[NewPipeExtractor bridge stderr]\n")
        sys.stderr.write(stderr)
        if not stderr.endswith("\n"):
            sys.stderr.write("\n")
    normalised = [_normalise_newpipe(row) for row in rows]
    per_item = [float(row["elapsed_ms"]) for row in rows if isinstance(row.get("elapsed_ms"), (int, float))]
    return (
        normalised,
        elapsed,
        {
            "bridge": str(bridge),
            "extractor_version": "0.26.5",
            "authentication": "anonymous",
            "jvm_processes": 1,
            "startup_and_shutdown_ms": max(0.0, elapsed * 1000.0 - sum(per_item)),
            "per_item_elapsed_ms": per_item,
            "stderr_bytes": len(stderr.encode("utf-8")),
        },
    )


def _invidious_instance(value: str) -> str:
    """Validate an explicitly selected Invidious instance without discovering alternatives."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise argparse.ArgumentTypeError("Invidious instance must be an absolute http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise argparse.ArgumentTypeError("Invidious instance URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("Invidious instance URL must not contain a query string or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _invidious_date(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y%m%d")


def _normalise_invidious(video_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Normalise documented Invidious video fields while retaining provider-native live signals."""
    return {
        "id": row.get("videoId") or video_id,
        "title": row.get("title"),
        "description": row.get("description"),
        "channel_id": row.get("authorId"),
        "duration": row.get("lengthSeconds"),
        "view_count": row.get("viewCount"),
        "upload_date": _invidious_date(row.get("published")),
        "category": row.get("genre"),
        "is_live": row.get("liveNow"),
        "keywords": row.get("keywords"),
        "ok": True,
        "source_signals": {
            "author": row.get("author"),
            "author_url": row.get("authorUrl"),
            "is_listed": row.get("isListed"),
            "live_now": row.get("liveNow"),
            "is_post_live_dvr": row.get("isPostLiveDvr"),
            "is_upcoming": row.get("isUpcoming"),
            "paid": row.get("paid"),
            "premium": row.get("premium"),
        },
    }


def _invidious_video_request(base: str, video_id: str, *, timeout: int) -> dict[str, Any]:
    """Request one video from the explicitly selected Invidious instance."""
    url = f"{base}/api/v1/videos/{quote(video_id, safe='')}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "yt-media-tools metadata benchmark"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - caller explicitly selects the remote instance.
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Invidious video endpoint returned a non-object JSON response")
    return payload


def _invidious(
    video_ids: list[str], *, instance: str | None = None
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """Acquire video metadata only from the instance explicitly selected by the caller."""
    configured = instance or os.environ.get(INVIDIOUS_INSTANCE_ENV)
    if not configured:
        raise RuntimeError(
            "Invidious benchmarking requires an explicitly configured instance via "
            "--invidious-instance or " + INVIDIOUS_INSTANCE_ENV
        )
    if not video_ids:
        raise RuntimeError("Invidious benchmarking requires at least one video ID")
    try:
        base = _invidious_instance(configured)
    except argparse.ArgumentTypeError as exc:
        raise RuntimeError(str(exc)) from exc

    # Capability preflight deliberately exercises the exact endpoint required by
    # the benchmark. A healthy /stats endpoint does not imply that /videos/:id
    # is enabled on a particular public deployment.
    probe_id = video_ids[0]
    emit_invocation(
        ToolInvocation(
            tool="invidious",
            operation="GET /api/v1/videos/:id",
            purpose="explicit instance video-API capability preflight",
            status="executing",
            arguments={"instance": base, "video_id": probe_id},
        )
    )
    preflight_started = time.perf_counter()
    try:
        probe_payload = _invidious_video_request(base, probe_id, timeout=INVIDIOUS_PREFLIGHT_TIMEOUT_SECONDS)
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = f"HTTP {exc.code}: {body or exc.reason}"
        raise RuntimeError(
            f"Invidious video API preflight failed for {base}: {detail}. "
            "The selected instance may be reachable while its video API is disabled or unavailable."
        ) from exc
    except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError(
            f"Invidious video API preflight failed for {base}: {exc}. "
            "Check the explicitly selected instance before running a benchmark corpus."
        ) from exc
    preflight_elapsed_ms = (time.perf_counter() - preflight_started) * 1000.0

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    item_times: list[float] = []
    started = time.perf_counter()
    for index, video_id in enumerate(video_ids):
        emit_invocation(
            ToolInvocation(
                tool="invidious",
                operation="GET /api/v1/videos/:id",
                purpose="known-video metadata benchmark",
                status="executing",
                arguments={"instance": base, "video_id": video_id},
            )
        )
        item_started = time.perf_counter()
        try:
            payload = (
                probe_payload
                if index == 0
                else _invidious_video_request(base, video_id, timeout=INVIDIOUS_REQUEST_TIMEOUT_SECONDS)
            )
            row = _normalise_invidious(video_id, payload)
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace").strip()
            message = f"Invidious HTTP {exc.code}: {body or exc.reason}"
            row = _failure_row(video_id, message, error_type=type(exc).__name__)
            failures.append({"id": video_id, "kind": row["failure"]["kind"], "error_type": type(exc).__name__})
        except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            row = _failure_row(video_id, str(exc), error_type=type(exc).__name__)
            failures.append({"id": video_id, "kind": row["failure"]["kind"], "error_type": type(exc).__name__})
        elapsed_ms = (time.perf_counter() - item_started) * 1000.0
        row["elapsed_ms"] = elapsed_ms
        item_times.append(elapsed_ms)
        rows.append(row)
    elapsed = time.perf_counter() - started
    return (
        rows,
        elapsed,
        {
            "instance": base,
            "authentication": "anonymous",
            "request_count": len(video_ids),
            "preflight_endpoint": "/api/v1/videos/:id",
            "preflight_video_id": probe_id,
            "preflight_elapsed_ms": preflight_elapsed_ms,
            "preflight_timeout_seconds": INVIDIOUS_PREFLIGHT_TIMEOUT_SECONDS,
            "request_timeout_seconds": INVIDIOUS_REQUEST_TIMEOUT_SECONDS,
            "preflight_reused_as_first_result": True,
            "per_item_elapsed_ms": item_times,
            "failures": failures,
        },
    )


def _piped_instance(value: str) -> str:
    """Validate an explicitly selected Piped API instance without discovering alternatives."""
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise argparse.ArgumentTypeError("Piped instance must be an absolute http:// or https:// URL")
    if parsed.username is not None or parsed.password is not None:
        raise argparse.ArgumentTypeError("Piped instance URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError("Piped instance URL must not contain a query string or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _piped_channel_id(uploader_url: Any) -> str | None:
    if not isinstance(uploader_url, str):
        return None
    match = re.fullmatch(r"/channel/([A-Za-z0-9_-]+)", uploader_url)
    return match.group(1) if match else None


def _piped_upload_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", value.strip())
    return "".join(match.groups()) if match else None


def _normalise_piped(video_id: str, row: dict[str, Any]) -> dict[str, Any]:
    """Normalise documented Piped stream fields and retain provider-native evidence."""
    return {
        "id": video_id,
        "title": row.get("title"),
        "description": row.get("description"),
        "channel_id": _piped_channel_id(row.get("uploaderUrl")),
        "duration": row.get("duration"),
        "view_count": row.get("views"),
        "upload_date": _piped_upload_date(row.get("uploadDate")),
        "category": None,
        "is_live": row.get("livestream"),
        "keywords": None,
        "ok": True,
        "source_signals": {
            "uploader": row.get("uploader"),
            "uploader_url": row.get("uploaderUrl"),
            "uploader_verified": row.get("uploaderVerified"),
            "upload_date_raw": row.get("uploadDate"),
            "likes": row.get("likes"),
            "dislikes": row.get("dislikes"),
            "livestream": row.get("livestream"),
            "subtitle_count": len(row.get("subtitles", [])) if isinstance(row.get("subtitles"), list) else None,
            "audio_stream_count": len(row.get("audioStreams", []))
            if isinstance(row.get("audioStreams"), list)
            else None,
            "video_stream_count": len(row.get("videoStreams", []))
            if isinstance(row.get("videoStreams"), list)
            else None,
        },
    }


def _piped_http_failure(exc: HTTPError) -> tuple[str, str]:
    """Classify a bounded Piped HTTP failure without echoing arbitrary remote diagnostics."""
    raw = exc.read().decode("utf-8", errors="replace").strip()
    message = raw
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        candidate = payload.get("message") or payload.get("error")
        if isinstance(candidate, str) and candidate.strip():
            message = candidate.strip().splitlines()[0]
    lowered = message.lower()
    if (
        "sign in to confirm" in lowered
        or "login_required" in lowered
        or "temporarily blocked anonymous watch access" in lowered
    ):
        kind = "upstream_authentication_required"
    elif exc.code in {401, 403}:
        kind = "api_access_denied"
    elif 500 <= exc.code < 600:
        kind = "provider_upstream_failure"
    else:
        kind = "provider_http_error"
    detail = message or str(exc.reason)
    if len(detail) > PIPED_ERROR_DETAIL_MAX_CHARS:
        detail = detail[: PIPED_ERROR_DETAIL_MAX_CHARS - 1].rstrip() + "…"
    return kind, f"HTTP {exc.code}: {detail}"


def _piped_stream_request(base: str, video_id: str, *, timeout: int) -> dict[str, Any]:
    """Request one video from the explicitly selected Piped API instance."""
    url = f"{base}/streams/{quote(video_id, safe='')}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "yt-media-tools metadata benchmark"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - caller explicitly selects the remote instance.
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Piped streams endpoint returned a non-object JSON response")
    return payload


def _piped(video_ids: list[str], *, instance: str | None = None) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """Acquire video metadata only from the Piped API instance explicitly selected by the caller."""
    configured = instance or os.environ.get(PIPED_INSTANCE_ENV)
    if not configured:
        raise RuntimeError(
            "Piped benchmarking requires an explicitly configured instance via --piped-instance or "
            + PIPED_INSTANCE_ENV
        )
    if not video_ids:
        raise RuntimeError("Piped benchmarking requires at least one video ID")
    try:
        base = _piped_instance(configured)
    except argparse.ArgumentTypeError as exc:
        raise RuntimeError(str(exc)) from exc

    probe_id = video_ids[0]
    emit_invocation(
        ToolInvocation(
            tool="piped",
            operation="GET /streams/:id",
            purpose="explicit instance streams-API capability preflight",
            status="executing",
            arguments={"instance": base, "video_id": probe_id},
        )
    )
    preflight_started = time.perf_counter()
    try:
        probe_payload = _piped_stream_request(base, probe_id, timeout=PIPED_PREFLIGHT_TIMEOUT_SECONDS)
    except HTTPError as exc:
        kind, detail = _piped_http_failure(exc)
        if kind == "upstream_authentication_required":
            guidance = "The Piped API is operational, but its upstream YouTube acquisition was rejected."
        elif kind == "api_access_denied":
            guidance = "The selected instance denied access to its streams API."
        else:
            guidance = "The selected instance reached its streams path but could not satisfy the metadata request."
        raise RuntimeError(f"Piped streams API preflight failed for {base} [{kind}]: {detail}. {guidance}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
        raise RuntimeError(
            f"Piped streams API preflight failed for {base}: {exc}. Check the explicitly selected instance before running a benchmark corpus."
        ) from exc
    preflight_elapsed_ms = (time.perf_counter() - preflight_started) * 1000.0

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    item_times: list[float] = []
    started = time.perf_counter()
    for index, video_id in enumerate(video_ids):
        emit_invocation(
            ToolInvocation(
                tool="piped",
                operation="GET /streams/:id",
                purpose="known-video metadata benchmark",
                status="executing",
                arguments={"instance": base, "video_id": video_id},
            )
        )
        item_started = time.perf_counter()
        try:
            payload = (
                probe_payload
                if index == 0
                else _piped_stream_request(base, video_id, timeout=PIPED_REQUEST_TIMEOUT_SECONDS)
            )
            row = _normalise_piped(video_id, payload)
        except HTTPError as exc:
            kind, detail = _piped_http_failure(exc)
            message = f"Piped {detail}"
            row = _failure_row(video_id, message, error_type=type(exc).__name__)
            row["failure"]["kind"] = kind
            failures.append({"id": video_id, "kind": kind, "error_type": type(exc).__name__})
        except (URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            row = _failure_row(video_id, str(exc), error_type=type(exc).__name__)
            failures.append({"id": video_id, "kind": row["failure"]["kind"], "error_type": type(exc).__name__})
        elapsed_ms = (time.perf_counter() - item_started) * 1000.0
        row["elapsed_ms"] = elapsed_ms
        item_times.append(elapsed_ms)
        rows.append(row)
    elapsed = time.perf_counter() - started
    return (
        rows,
        elapsed,
        {
            "instance": base,
            "authentication": "anonymous",
            "request_count": len(video_ids),
            "preflight_endpoint": "/streams/:id",
            "preflight_video_id": probe_id,
            "preflight_elapsed_ms": preflight_elapsed_ms,
            "preflight_timeout_seconds": PIPED_PREFLIGHT_TIMEOUT_SECONDS,
            "request_timeout_seconds": PIPED_REQUEST_TIMEOUT_SECONDS,
            "preflight_reused_as_first_result": True,
            "per_item_elapsed_ms": item_times,
            "failures": failures,
        },
    )


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


def _ytdlp(video_ids: list[str], *, profile: str = "core") -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
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
            successful_rows.append(_normalise_ytdlp(value, include_extended=profile == "full"))
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
            "measurement_profile": profile,
            "stderr_bytes": len(result.stderr.encode("utf-8")),
            "items": [
                {"id": video_id, "message": message, "kind": _classify_failure(message)}
                for video_id, message in per_id_diagnostics.items()
            ],
        },
    )


def _run_provider(
    name: str,
    video_ids: list[str],
    profile: str,
    *,
    invidious_instance: str | None = None,
    piped_instance: str | None = None,
) -> tuple[list[dict[str, Any]], float, dict[str, Any]]:
    """Run one provider under a declared provider-neutral measurement profile."""
    if profile not in PROFILE_SUPPORT[name]:
        raise RuntimeError(f"provider {name} does not support measurement profile {profile}")
    if name == "pytubefix":
        return _pytubefix(video_ids, profile=profile)
    if name == "ytdlp":
        return _ytdlp(video_ids, profile=profile)
    if name == "newpipe-extractor":
        return _newpipe_extractor(video_ids)
    if name == "invidious":
        return _invidious(video_ids, instance=invidious_instance)
    if name == "piped":
        return _piped(video_ids, instance=piped_instance)
    rows, elapsed, diagnostics = RUNNERS[name](video_ids)
    diagnostics = dict(diagnostics)
    diagnostics["measurement_profile"] = profile
    return rows, elapsed, diagnostics


RUNNERS: dict[str, Callable[[list[str]], tuple[list[dict[str, Any]], float, dict[str, Any]]]] = {
    "youtubejs": _youtubejs,
    "youtube-innertube": _youtube_innertube,
    "pytubefix": _pytubefix,
    "newpipe-extractor": _newpipe_extractor,
    "invidious": _invidious,
    "piped": _piped,
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


class _DescriptionTextExtractor(HTMLParser):
    """Extract human-visible description text without provider-specific HTML markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _normalise_description_text(value: Any) -> str | None:
    """Return a conservative text-only form for cross-provider description analysis."""
    if not isinstance(value, str):
        return None
    parser = _DescriptionTextExtractor()
    parser.feed(value)
    parser.close()
    text = html.unescape(" ".join(parser.parts))
    return " ".join(text.split())


def _description_analysis(candidate: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Describe representation-level description differences without claiming semantic equivalence."""
    left_raw = candidate.get("description")
    right_raw = reference.get("description")
    left = _normalise_description_text(left_raw)
    right = _normalise_description_text(right_raw)
    if left is None or right is None:
        return {"status": "missing", "text_equal": False, "similarity_ratio": None}
    return {
        "status": "exact" if left_raw == right_raw else ("text_equal" if left == right else "different"),
        "text_equal": left == right,
        "similarity_ratio": SequenceMatcher(None, left, right, autojunk=False).ratio(),
        "candidate_text_length": len(left),
        "reference_text_length": len(right),
    }


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
    return {
        "id": video_id,
        "ok": True,
        "status": "compared",
        "agreement": agreement,
        "deltas": deltas,
        "description_analysis": _description_analysis(candidate, reference),
    }


def _video_id(value: str) -> str:
    """Reject malformed benchmark IDs before providers can reinterpret them differently."""
    if any(character.isspace() for character in value):
        raise argparse.ArgumentTypeError("video ID must not contain whitespace")
    return value


def _provider_names(value: str) -> list[str]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    invalid = [name for name in names if name not in PROVIDERS]
    if invalid:
        raise argparse.ArgumentTypeError(f"unknown provider(s): {', '.join(invalid)}")
    if "ytdlp" not in names:
        names.append("ytdlp")
    return names


def _redact_secrets(value: Any, secrets: tuple[str | None, ...]) -> Any:
    """Remove credential values from third-party diagnostics before they enter reports."""
    active = tuple(secret for secret in secrets if secret)
    if isinstance(value, str):
        for secret in active:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact_secrets(item, active) for item in value]
    if isinstance(value, dict):
        return {key: _redact_secrets(item, active) for key, item in value.items()}
    return value


def _assert_secrets_absent(payload: Any, secrets: tuple[str | None, ...]) -> None:
    """Fail closed if any credential material reaches serialisable benchmark output."""
    serialised = json.dumps(payload, ensure_ascii=False)
    if any(secret and secret in serialised for secret in secrets):
        raise RuntimeError("YouTube.js cookie material reached benchmark output; refusing to serialise report")


def _youtubejs_cookie_from_environment(enabled: bool) -> str | None:
    if not enabled:
        return None
    cookie = os.environ.get(YOUTUBEJS_COOKIE_ENV)
    if not cookie:
        raise RuntimeError(f"--youtubejs-cookie requires {YOUTUBEJS_COOKIE_ENV} to be set")
    return cookie


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id", nargs="+", type=_video_id, help="YouTube video IDs forming the benchmark corpus")
    parser.add_argument(
        "--providers",
        type=_provider_names,
        default=list(DEFAULT_PROVIDERS),
        help="comma-separated providers (youtubejs,youtube-innertube,pytubefix,newpipe-extractor,invidious,piped,ytdlp); ytdlp is always included as the reference",
    )
    parser.add_argument("--json", action="store_true", help="emit the complete machine-readable benchmark result")
    parser.add_argument(
        "--invidious-instance",
        type=_invidious_instance,
        metavar="URL",
        help=f"explicit Invidious instance for the invidious provider; alternatively set {INVIDIOUS_INSTANCE_ENV}",
    )
    parser.add_argument(
        "--piped-instance",
        type=_piped_instance,
        metavar="URL",
        help=f"explicit Piped API instance for the piped provider; alternatively set {PIPED_INSTANCE_ENV}",
    )
    parser.add_argument(
        "--debug-external", action="store_true", help="show redacted external-tool invocations on stderr"
    )
    parser.add_argument(
        "--profile",
        choices=MEASUREMENT_PROFILES,
        default="core",
        help="provider-neutral acquisition profile; full is available only where the provider can satisfy the extended capability contract",
    )
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument(
        "--youtubejs-cookie",
        action="store_true",
        help=f"also benchmark YouTube.js with a Cookie header from {YOUTUBEJS_COOKIE_ENV}",
    )
    auth.add_argument(
        "--youtubejs-cookies",
        type=Path,
        metavar="FILE",
        help="also benchmark YouTube.js using applicable cookies from a Netscape cookies file",
    )
    args = parser.parse_args()
    configure_external_diagnostics(enabled=args.debug_external)

    cookie = _youtubejs_cookie_from_environment(args.youtubejs_cookie)
    cookie_values: tuple[str, ...] = ()
    if args.youtubejs_cookies is not None:
        try:
            cookie, cookie_values = cookie_header_from_netscape_file(args.youtubejs_cookies)
        except CookieFileError as exc:
            parser.error(str(exc))
    provider_results: dict[str, dict[str, Any]] = {}
    run_names: list[str] = []
    for name in args.providers:
        rows, elapsed, diagnostics = _run_provider(
            name,
            args.video_id,
            args.profile,
            invidious_instance=args.invidious_instance,
            piped_instance=args.piped_instance,
        )
        provider_results[name] = {
            "elapsed_seconds": elapsed,
            "rows": rows,
            "diagnostics": diagnostics,
            "summary": _provider_summary(rows, len(args.video_id)),
        }
        run_names.append(name)
        if name == "youtubejs" and cookie is not None:
            authenticated_rows, authenticated_elapsed, authenticated_diagnostics = _youtubejs(
                args.video_id, cookie=cookie, secret_values=cookie_values
            )
            variant = "youtubejs-cookie"
            provider_results[variant] = {
                "elapsed_seconds": authenticated_elapsed,
                "rows": authenticated_rows,
                "diagnostics": authenticated_diagnostics,
                "summary": _provider_summary(authenticated_rows, len(args.video_id)),
            }
            run_names.append(variant)

    reference = _index(provider_results["ytdlp"]["rows"])
    comparisons: dict[str, list[dict[str, Any]]] = {}
    for name in run_names:
        if name == "ytdlp":
            continue
        candidate = _index(provider_results[name]["rows"])
        comparisons[name] = [
            _comparison(video_id, candidate.get(video_id, {}), reference.get(video_id, {}))
            for video_id in args.video_id
        ]

    variant_comparisons: dict[str, list[dict[str, Any]]] = {}
    if "youtubejs-cookie" in provider_results and "youtubejs" in provider_results:
        anonymous = _index(provider_results["youtubejs"]["rows"])
        authenticated = _index(provider_results["youtubejs-cookie"]["rows"])
        variant_comparisons["youtubejs-cookie-against-anonymous"] = [
            _comparison(video_id, authenticated.get(video_id, {}), anonymous.get(video_id, {}))
            for video_id in args.video_id
        ]

    payload = {
        "schema_version": 11,
        "measurement_profile": args.profile,
        "profile_support": {name: sorted(PROFILE_SUPPORT[name]) for name in PROVIDERS},
        "corpus_size": len(args.video_id),
        "providers": provider_results,
        "comparisons": comparisons,
        "variant_comparisons": variant_comparisons,
    }
    _assert_secrets_absent(payload, (cookie, *cookie_values))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Corpus: {len(args.video_id)} videos")
        for name in run_names:
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
