from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "python" / "yt_media_tools" / "youtubejs_bridge.mjs"


def test_bridge_filters_only_named_routine_parser_warning_and_has_diagnostic_escape_hatch() -> None:
    source = BRIDGE.read_text(encoding="utf-8")
    assert "[YOUTUBEJS][Text]: Unable to find matching run for attachment run. Skipping" in source
    assert "YT_DISCOVER_YOUTUBEJS_DIAGNOSTICS" in source
    assert "console.warn =" in source
    assert "console.error =" not in source
    assert "process.stderr.write(`[yt-discover:youtubejs] ${message}\\n`)" in source


def test_proxy_fetch_adapter_accepts_platform_native_request() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is unavailable")
    if not (ROOT / "node_modules" / "node-fetch").is_dir():
        pytest.skip("The optional YouTube.js adapter Node dependencies are not installed")

    script = """
import { nodeFetchArguments } from %s;
import { Request as NodeFetchRequest } from 'node-fetch';
const controller = new AbortController();
const request = new Request('https://www.youtube.com/@cubechemistry', {
  method: 'POST',
  signal: controller.signal,
});
const headers = new Headers({ 'Content-Type': 'application/json' });
const [input, init] = nodeFetchArguments(request, {
  body: '{"query":"cubechemistry"}',
  headers,
  redirect: 'manual',
});
const adaptedRequest = new NodeFetchRequest(input, init);
process.stdout.write(JSON.stringify({
  input: adaptedRequest.url,
  method: adaptedRequest.method,
  body: init.body,
  headersPreserved: init.headers === headers,
  redirect: init.redirect,
  signalPreserved: init.signal === request.signal,
}));
""" % json.dumps(BRIDGE.as_uri())

    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "input": "https://www.youtube.com/@cubechemistry",
        "method": "POST",
        "body": '{"query":"cubechemistry"}',
        "headersPreserved": True,
        "redirect": "manual",
        "signalPreserved": True,
    }
