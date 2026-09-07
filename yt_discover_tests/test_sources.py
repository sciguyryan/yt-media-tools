import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_sources():
    spec = importlib.util.spec_from_file_location("yt_sources_test", ROOT / "yt_sources.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


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
