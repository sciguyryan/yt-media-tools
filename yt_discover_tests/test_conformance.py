"""End-to-end yt-sql conformance tests using independent Python semantic oracles."""

from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from yt_discover_tests.conformance.cases import CASES, LANGUAGE_FEATURES, ConformanceCase
from yt_discover_tests.conformance.generate_dataset import (
    DATASET_SEED,
    GENERATOR_VERSION,
    PROFILE_SIZES,
    GENERATED_AT,
    SOURCE_URL,
    build_records,
    dataset_digest,
    generate_profiles,
    payload,
)
from yt_discover_tests.conformance.oracle import OracleQuery, serialise
from yt_media_tools.dates import DateContext
from yt_media_tools.metadata import normalise_record
from yt_media_tools.optimizer import optimise_query
from yt_media_tools.output import write_records
from yt_media_tools.query import apply_query, parse_query, resolve_query
from yt_media_tools.schema import QuerySchema

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "yt_discover_tests" / "conformance"
GENERATOR = CONF / "generate_dataset.py"
SPEC = CONF / "dataset-spec-v3.json"
CLI = ROOT / "yt-discover.py"


def _oracle_records(records: list[dict[str, object]]) -> list[dict[str, Any]]:
    """Add source_index exactly as source enumeration does, without production helpers."""
    return [dict(record, source_index=index) for index, record in enumerate(records, start=1)]


def _run_case(cache: Path, case: ConformanceCase) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(CLI),
        "--offline",
        "--cache",
        str(cache),
        "--tab",
        "videos",
        *case.cli_args,
        case.query,
        "--format",
        case.output_format,
    ]
    for parameter in case.params:
        command.extend(["--param", parameter])
    return subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)


def _engine_case_output(records: list[dict[str, object]], case: ConformanceCase) -> str:
    """Execute one semantic case through production language components in-process."""
    if case.params:
        raise AssertionError("parameter-binding cases must execute through the CLI")
    date_format = "dmy"
    for index, arg in enumerate(case.cli_args):
        if arg == "--date-format" and index + 1 < len(case.cli_args):
            date_format = case.cli_args[index + 1]
    context = DateContext(date_order=date_format, now=datetime.fromisoformat(GENERATED_AT))
    production_records = []
    for source_index, raw in enumerate(records, start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        production_records.append(record)
    parsed = parse_query(case.query)
    resolved = resolve_query(parsed, QuerySchema(production_records), context)
    resolved = optimise_query(resolved).query
    selected = apply_query(production_records, resolved)
    stream = io.StringIO()
    with redirect_stdout(stream):
        write_records(selected, resolved, case.output_format, None, explicit_select=bool(parsed.select))
    return stream.getvalue()


def _engine_case_queries(records: list[dict[str, object]], case: ConformanceCase):
    """Resolve one semantic case and return both original and optimised production queries."""
    date_format = "dmy"
    for index, arg in enumerate(case.cli_args):
        if arg == "--date-format" and index + 1 < len(case.cli_args):
            date_format = case.cli_args[index + 1]
    context = DateContext(date_order=date_format, now=datetime.fromisoformat(GENERATED_AT))
    production_records = []
    for source_index, raw in enumerate(records, start=1):
        record = normalise_record(dict(raw))
        record["source_index"] = source_index
        production_records.append(record)
    parsed = parse_query(case.query)
    resolved = resolve_query(parsed, QuerySchema(production_records), context)
    return production_records, parsed, resolved, optimise_query(resolved).query


def _assert_case(dataset: Any, case: ConformanceCase) -> None:
    expected_rows = case.oracle(_oracle_records(dataset.records))
    expected = serialise(expected_rows, case.output_format, case.columns)
    if case.execution == "cli":
        proc = _run_case(dataset.cache_path, case)
        assert proc.returncode == 0, (
            f"yt-sql case {case.name!r} failed on {dataset.name} "
            f"(generator v{dataset.generator_version}, seed {dataset.seed}, size {dataset.size}, "
            f"digest {dataset.digest}):\n{proc.stderr}"
        )
        actual = proc.stdout
    else:
        actual = _engine_case_output(dataset.records, case)
    assert actual == expected, (
        f"yt-sql/oracle disagreement for {case.name!r} on {dataset.name} "
        f"(generator v{dataset.generator_version}, seed {dataset.seed}, size {dataset.size}, "
        f"digest {dataset.digest})"
    )


@pytest.mark.parametrize("profile", ("small", "normal"))
def test_optimizer_preserves_all_routine_semantic_cases(profile: str) -> None:
    """Every current semantic query must behave identically before and after optimisation."""
    records = build_records(PROFILE_SIZES[profile])
    for case in CASES:
        if case.params or case.execution == "cli":
            continue
        production_records, parsed, original, optimised = _engine_case_queries(records, case)
        assert apply_query(production_records, original) == apply_query(production_records, optimised), case.name

        original_stream = io.StringIO()
        with redirect_stdout(original_stream):
            write_records(
                apply_query(production_records, original),
                original,
                case.output_format,
                None,
                explicit_select=bool(parsed.select),
            )
        optimised_stream = io.StringIO()
        with redirect_stdout(optimised_stream):
            write_records(
                apply_query(production_records, optimised),
                optimised,
                case.output_format,
                None,
                explicit_select=bool(parsed.select),
            )
        assert optimised_stream.getvalue() == original_stream.getvalue(), case.name


def test_language_feature_manifest_is_fully_covered() -> None:
    covered = {feature for case in CASES for feature in case.features}
    assert covered == LANGUAGE_FEATURES, (
        f"missing features: {sorted(LANGUAGE_FEATURES - covered)}; "
        f"unregistered features: {sorted(covered - LANGUAGE_FEATURES)}"
    )
    assert len({case.name for case in CASES}) == len(CASES)


def test_profile_sizes_are_ordered_and_centrally_defined() -> None:
    assert tuple(PROFILE_SIZES) == ("small", "normal", "large", "huge")
    sizes = list(PROFILE_SIZES.values())
    assert sizes == sorted(sizes)
    assert len(set(sizes)) == len(sizes)
    assert sizes[0] >= 60


@pytest.mark.parametrize("profile", ("small", "normal"))
def test_routine_profiles_have_exact_requested_cardinality(profile: str) -> None:
    records = build_records(PROFILE_SIZES[profile])
    assert len(records) == PROFILE_SIZES[profile]
    assert len({str(record["id"]) for record in records}) == PROFILE_SIZES[profile]


@pytest.mark.scale
def test_large_profile_has_exact_requested_cardinality() -> None:
    records = build_records(PROFILE_SIZES["large"])
    assert len(records) == PROFILE_SIZES["large"]
    assert len({str(record["id"]) for record in records}) == PROFILE_SIZES["large"]


@pytest.mark.stress
def test_huge_profile_has_exact_requested_cardinality() -> None:
    records = build_records(PROFILE_SIZES["huge"])
    assert len(records) == PROFILE_SIZES["huge"]
    assert len({str(record["id"]) for record in records}) == PROFILE_SIZES["huge"]


def test_routine_profiles_are_exact_prefixes() -> None:
    normal = build_records(PROFILE_SIZES["normal"])
    assert build_records(PROFILE_SIZES["small"]) == normal[: PROFILE_SIZES["small"]]


@pytest.mark.scale
def test_large_profile_extends_normal_as_exact_prefix() -> None:
    large = build_records(PROFILE_SIZES["large"])
    assert build_records(PROFILE_SIZES["normal"]) == large[: PROFILE_SIZES["normal"]]


@pytest.mark.stress
def test_huge_profile_extends_large_as_exact_prefix() -> None:
    huge = build_records(PROFILE_SIZES["huge"])
    assert build_records(PROFILE_SIZES["large"]) == huge[: PROFILE_SIZES["large"]]


def test_generator_is_deterministic_for_version_seed_and_size() -> None:
    first = build_records(PROFILE_SIZES["normal"], seed=DATASET_SEED)
    second = build_records(PROFILE_SIZES["normal"], seed=DATASET_SEED)
    assert first == second
    assert dataset_digest(first) == dataset_digest(second)


def test_different_seed_changes_generated_population_without_changing_size() -> None:
    size = PROFILE_SIZES["normal"]
    first = build_records(size, seed=DATASET_SEED)
    second = build_records(size, seed=DATASET_SEED + 1)
    assert len(first) == len(second) == size
    assert dataset_digest(first) != dataset_digest(second)


def test_payload_records_reproduction_identity() -> None:
    value = payload(PROFILE_SIZES["small"], seed=DATASET_SEED, profile="small")
    assert value["generator_version"] == GENERATOR_VERSION
    assert value["seed"] == DATASET_SEED
    assert value["profile"] == "small"
    assert value["record_count"] == PROFILE_SIZES["small"]
    assert value["record_digest_sha256"] == dataset_digest(value["records"])


def test_dataset_contains_required_semantic_edge_classes() -> None:
    rows = build_records(PROFILE_SIZES["small"])
    assert any(row["release_timestamp"] is None for row in rows)
    assert any(row["view_count"] is None for row in rows)
    assert {3599, 3600, 3601}.issubset({row["duration"] for row in rows})
    assert len({row["title"] for row in rows}) < len(rows)
    titles = [str(row["title"]) for row in rows]
    assert any("café" in title for title in titles)
    assert any("Café" in title for title in titles)
    assert any("😀" in title for title in titles)
    assert any("👩‍👩‍👧‍👦" in title for title in titles)
    assert any("Σ σ ς" in title for title in titles)
    assert any("İ I ı i" in title for title in titles)
    assert any("Straße" in title for title in titles)
    assert any("مرحبا" in title for title in titles)
    assert any("שלום" in title for title in titles)
    assert any("\u2028" in title for title in titles)
    assert any(".*" in title for title in titles)
    assert any(row["availability"] == "private" for row in rows)
    assert any(row["live_status"] == "is_live" for row in rows)
    assert any(row["live_status"] == "was_live" for row in rows)
    assert any(row["upload_date"] is None for row in rows)
    assert any(row["fixture_nullable"] is None for row in rows)


@pytest.mark.scale
def test_large_generated_population_preserves_controlled_distributions() -> None:
    rows = build_records(PROFILE_SIZES["large"])
    assert sum(row["duration"] is None for row in rows) > 50
    assert sum(row["view_count"] is None for row in rows) > 50
    assert sum(row["upload_date"] is None for row in rows) > 50
    assert sum(row["release_timestamp"] is None for row in rows) > 50
    assert sum(row["availability"] == "private" for row in rows) > 50
    assert len({row["fixture_group"] for row in rows}) >= 17
    assert len({row["channel_id"] for row in rows}) >= 11


def test_generator_spec_matches_implementation() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    assert spec["generator_version"] == GENERATOR_VERSION
    assert spec["default_seed"] == DATASET_SEED
    assert spec["profiles"] == PROFILE_SIZES
    assert spec["source_url"] == SOURCE_URL


def test_manual_exact_size_cli_generation(tmp_path: Path) -> None:
    json_path = tmp_path / "dataset.json"
    cache_path = tmp_path / "cache.sqlite3"
    proc = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--size",
            "137",
            "--json",
            str(json_path),
            "--cache",
            str(cache_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    generated = json.loads(json_path.read_text(encoding="utf-8"))
    assert generated["record_count"] == 137
    assert generated["profile"] is None
    assert cache_path.exists()


def test_generate_all_profiles_contract_without_expensive_duplicate_corpora(tmp_path: Path) -> None:
    output = tmp_path / "profiles"
    miniature_profiles = {"small": 3, "normal": 5, "large": 7, "huge": 9}
    generate_profiles(output, profiles=miniature_profiles, progress=False)
    for profile, size in miniature_profiles.items():
        dataset_path = output / profile / "dataset.json"
        cache_path = output / profile / "metadata.sqlite3"
        assert dataset_path.exists(), profile
        assert cache_path.exists(), profile
        generated = json.loads(dataset_path.read_text(encoding="utf-8"))
        assert generated["profile"] == profile
        assert generated["record_count"] == size

    help_proc = subprocess.run(
        [sys.executable, str(GENERATOR), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_proc.returncode == 0
    for profile in PROFILE_SIZES:
        assert profile in help_proc.stdout
    assert "--size" in help_proc.stdout
    assert "--output-dir" in help_proc.stdout


def test_oracle_module_does_not_import_production_query_engine() -> None:
    forbidden_prefixes = {
        "yt_media_tools.query",
        "yt_media_tools.planner",
        "yt_media_tools.output",
        "yt_media_tools.metadata",
        "yt_media_tools.schema",
    }
    for path in (CONF / "oracle.py", CONF / "cases.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        assert not any(
            imported_name == forbidden or imported_name.startswith(forbidden + ".")
            for imported_name in imported
            for forbidden in forbidden_prefixes
        ), f"oracle independence violation in {path.name}: {sorted(imported)}"


def test_oracle_chain_operators_have_obvious_collection_semantics() -> None:
    rows = [
        {"id": "a", "value": 3, "group": "x"},
        {"id": "b", "value": None, "group": "x"},
        {"id": "c", "value": 1, "group": "y"},
        {"id": "d", "value": 2, "group": "x"},
    ]
    result = (
        OracleQuery(rows)
        .where(lambda row: row["group"] == "x")
        .order_by(lambda row: row["value"])
        .select(lambda row: row["id"])
        .skip(1)
        .take(2)
        .to_list()
    )
    assert result == ["a", "b"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_small_profile_matches_independent_oracle(conformance_small: Any, case: ConformanceCase) -> None:
    _assert_case(conformance_small, case)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_normal_profile_matches_independent_oracle(conformance_normal: Any, case: ConformanceCase) -> None:
    _assert_case(conformance_normal, case)


@pytest.mark.scale
def test_large_profile_multikey_ordering_matches_oracle(conformance_large: Any) -> None:
    case = next(case for case in CASES if case.name == "chronological_same_day_subsort")
    _assert_case(conformance_large, case)


@pytest.mark.stress
def test_huge_profile_filter_sort_limit_matches_oracle(conformance_huge: Any) -> None:
    case = next(case for case in CASES if case.name == "offset_limit")
    _assert_case(conformance_huge, case)


@pytest.mark.parametrize(
    "case_name",
    (
        "source_order_limit",
        "contains_case_insensitive",
        "scalar_functions_and_alias_order",
        "raw_dynamic_field",
        "date_local_mdy",
        "auto_multiple_output",
        "legacy_urls_output",
    ),
)
def test_representative_cases_match_oracle_through_real_cli(conformance_small: Any, case_name: str) -> None:
    case = next(item for item in CASES if item.name == case_name)
    expected = serialise(case.oracle(_oracle_records(conformance_small.records)), case.output_format, case.columns)
    proc = _run_case(conformance_small.cache_path, case)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == expected


def test_custom_size_dataset_can_drive_same_oracle(conformance_dataset_factory: Any) -> None:
    dataset = conformance_dataset_factory(size=257)
    case = next(case for case in CASES if case.name == "convoluted_existing_language")
    _assert_case(dataset, case)


def test_same_semantic_case_survives_different_seed(conformance_dataset_factory: Any) -> None:
    dataset = conformance_dataset_factory(size=389, seed=27182818)
    case = next(case for case in CASES if case.name == "offset_limit")
    _assert_case(dataset, case)


def test_offline_conformance_does_not_require_acquisition_tools(conformance_small: Any, tmp_path: Path) -> None:
    case = CASES[0]
    env = os.environ.copy()
    env["PATH"] = str(tmp_path)
    command = [
        sys.executable,
        str(CLI),
        "--offline",
        "--cache",
        str(conformance_small.cache_path),
        "--tab",
        "videos",
        case.query,
        "--format",
        case.output_format,
    ]
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, env=env)
    assert proc.returncode == 0, proc.stderr
    expected = serialise(case.oracle(_oracle_records(conformance_small.records)), case.output_format, case.columns)
    assert proc.stdout == expected


def test_ephemeral_cache_exercises_field_aware_freshness(conformance_small: Any) -> None:
    from yt_media_tools.cache import MetadataCache

    with MetadataCache(conformance_small.cache_path) as cache:
        item = cache.get(SOURCE_URL, "vid001")
        assert item is not None
        reference_now = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
        assert cache.is_fresh(item, {"upload_date", "release_timestamp", "duration"}, now=reference_now)
        assert not cache.is_fresh(item, {"view_count"}, now=reference_now)
