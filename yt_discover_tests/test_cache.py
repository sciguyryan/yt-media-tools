import importlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_cache():
    return importlib.import_module("yt_media_tools.cache")


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
