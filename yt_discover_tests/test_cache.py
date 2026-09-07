import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_cache():
    spec = importlib.util.spec_from_file_location("yt_cache_test", ROOT / "yt_cache.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def test_incremental_append_requires_overlap(tmp_path):
    cache = load_cache()
    connection = cache.connect(tmp_path / "cache.sqlite3")
    cache.store_source(
        connection,
        "source",
        [{"id": "c"}, {"id": "b"}, {"id": "a"}],
        backend="yt-dlp",
    )

    try:
        cache.append_new_entries(
            connection,
            "source",
            [{"id": "z"}],
            backend="yt-dlp",
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError("disjoint incremental observation was accepted")

    rows = cache.load_source(connection, "source", allow_stale=True)
    assert [row["id"] for row in rows] == ["c", "b", "a"]
