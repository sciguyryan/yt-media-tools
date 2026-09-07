from yt_discover_tests.conformance.dataset import GENERATOR_VERSION, SEED, generate_rows


def test_conformance_dataset_is_deterministic():
    assert GENERATOR_VERSION == 1
    assert SEED == 31415926
    assert generate_rows() == generate_rows()


def test_conformance_dataset_contains_edge_cases():
    rows = generate_rows()
    assert len(rows) == 4
    assert rows[0]["date"] == rows[1]["date"]
    assert any(row["duration"] is None for row in rows)
    assert any(row["uploader"] is None for row in rows)
    assert any(row["date"] is None for row in rows)
    assert any(row["live"] is True for row in rows)
