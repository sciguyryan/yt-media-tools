import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_sources():
    return importlib.import_module("yt_media_tools.sources")


def test_youtubejs_unexpected_result_type_raises_type_error(monkeypatch):
    sources = load_sources()

    class Completed:
        returncode = 0
        stdout = '{"unexpected": "object"}'
        stderr = ""

    monkeypatch.setattr(sources.subprocess, "run", lambda *args, **kwargs: Completed())

    try:
        sources.enumerate_youtubejs("source")
    except TypeError as exc:
        assert "unexpected result" in str(exc)
    else:
        raise AssertionError("unexpected YouTube.js result type was accepted")
