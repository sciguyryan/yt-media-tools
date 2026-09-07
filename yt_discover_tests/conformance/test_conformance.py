import json
from pathlib import Path

import pytest

from yt_discover_tests.conformance.dataset import (
    GENERATOR_VERSION,
    PROFILE_SIZES,
    SEED,
    generate_rows,
    resolve_size,
)
from yt_discover_tests.conformance.oracle import distinct, filter_equals, order_by, project


def test_generator_version_and_seed_are_stable():
    assert GENERATOR_VERSION == 2
    assert SEED == 31415926


@pytest.mark.parametrize("profile", ["small", "normal", "large", "huge"])
def test_named_profiles_generate_expected_size(profile):
    assert len(generate_rows(profile)) == PROFILE_SIZES[profile]


def test_exact_size_generation_is_supported():
    assert len(generate_rows(exact_size=37)) == 37


def test_exact_size_generation_is_deterministic():
    assert generate_rows(exact_size=50) == generate_rows(exact_size=50)


def test_seed_changes_generated_content_but_not_shape():
    first = generate_rows(exact_size=20, seed=SEED)
    second = generate_rows(exact_size=20, seed=SEED + 1)

    assert [row["id"] for row in first] == [row["id"] for row in second]
    assert first != second


def test_invalid_profile_is_rejected():
    with pytest.raises(ValueError):
        resolve_size("enormous")


def test_invalid_exact_size_is_rejected():
    with pytest.raises(ValueError):
        generate_rows(exact_size=0)


def test_oracle_projection_and_filtering_are_independent_helpers():
    rows = generate_rows("small")
    expected = project(filter_equals(rows, "uploader", "Example One"), ("id", "title"))

    assert expected == [
        {"id": "video00000", "title": "Alpha Launch"},
        {"id": "video00004", "title": "Epsilon Notes"},
        {"id": "video00008", "title": "Gamma Archive"},
    ]


def test_oracle_ordering_and_distinct_are_deterministic():
    rows = [
        {"id": "b"},
        {"id": "a"},
        {"id": "a"},
    ]
    assert distinct(order_by(rows, "id")) == [{"id": "a"}, {"id": "b"}]


def test_golden_fixture_is_well_formed():
    path = Path(__file__).with_name("golden.json")
    data = json.loads(path.read_text())

    assert data["cases"]
    assert {case["profile"] for case in data["cases"]} == {"small"}
    assert all(case["query"].startswith("SELECT ") for case in data["cases"])
    assert all(isinstance(case["expected"], list) for case in data["cases"])
