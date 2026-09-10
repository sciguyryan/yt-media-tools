"""Static relation and branch simplification proofs."""

from dataclasses import replace
import json
import os
import subprocess
import sys
from pathlib import Path

from yt_media_tools.dates import DateContext
from yt_media_tools.planner import plan_query, plan_source_boundaries
from yt_media_tools.query import parse_query, query_physical_source_requests
from yt_media_tools.relation_simplification import plan_relation_simplification
from yt_media_tools.source_capabilities import (
    STRUCTURALLY_UNSUPPORTED,
    FieldCapability,
    selected_facet_capabilities,
)
from yt_media_tools.sources import resolve_source_request


def _source(name: str = "@example"):
    return resolve_source_request(name, facet="videos")


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "yt-discover.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _unsupported_duration_facet():
    base = selected_facet_capabilities(_source())
    unsupported = FieldCapability(
        "duration",
        "unavailable",
        "unavailable",
        "unavailable",
        logical_kind="duration",
        structural_support=STRUCTURALLY_UNSUPPORTED,
    )
    return replace(base, field_overrides=base.field_overrides + (unsupported,))


def test_incompatible_equality_and_bound_prove_where_relation_empty() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE view_count = 5 AND view_count > 10")
    relation = plan_relation_simplification(query, source=_source())

    assert relation.empty
    assert "WHERE is proven never TRUE" in relation.reason
    assert relation.proofs
    assert all(proof.proven for proof in relation.proofs)


def test_incompatible_closed_and_open_bounds_prove_where_relation_empty() -> None:
    query = parse_query("SELECT id FROM @example OF videos WHERE view_count >= 10 AND view_count < 10")
    relation = plan_relation_simplification(query, source=_source())

    assert relation.empty


def test_constant_false_having_proves_relation_empty() -> None:
    query = parse_query("SELECT uploader, COUNT(*) AS n FROM @example OF videos GROUP BY uploader HAVING 1 = 0")
    relation = plan_relation_simplification(query, source=_source())

    assert relation.empty
    assert relation.having_truth == "false"
    assert "HAVING is proven never TRUE" in relation.reason


def test_constant_true_having_is_redundant_but_not_empty() -> None:
    query = parse_query("SELECT uploader, COUNT(*) AS n FROM @example OF videos GROUP BY uploader HAVING 1 = 1")
    relation = plan_relation_simplification(query, source=_source())

    assert not relation.empty
    assert relation.having_redundant
    assert relation.having_truth == "true"


def test_structurally_true_where_is_removed_from_physical_filter(monkeypatch) -> None:
    import yt_media_tools.optimizer_proofs as proofs

    monkeypatch.setattr(
        proofs,
        "selected_facet_capabilities",
        lambda source: _unsupported_duration_facet(),
    )
    query = parse_query("SELECT id FROM @example OF videos WHERE duration IS NULL")
    request = query_physical_source_requests(query)
    boundaries = plan_source_boundaries(
        query,
        requests=request,
        sources=(_source(),),
        dates=DateContext(),
    )

    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert not boundary.branch_empty
    assert boundary.redundant_where_uses == 1
    assert boundary.combined_predicate is None
    assert boundary.required_fields == frozenset({"id"})


def test_empty_union_branch_skips_its_physical_source() -> None:
    query = parse_query(
        "SELECT id FROM @alpha WHERE view_count = 5 AND view_count > 10 "
        "UNION ALL SELECT id FROM @beta WHERE title LIKE 'x%'"
    )
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    boundaries = plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DateContext(),
    )

    alpha = next(branch for branch in boundaries if branch.source_name == "@alpha")
    beta = next(branch for branch in boundaries if branch.source_name == "@beta")
    assert alpha.branch_empty
    assert alpha.acquisition.mode == "skip"
    assert alpha.eliminated_uses == 1
    assert beta.acquisition.mode != "skip"


def test_empty_same_source_union_use_does_not_contribute_fields() -> None:
    query = parse_query(
        "SELECT duration FROM @alpha WHERE view_count = 5 AND view_count > 10 "
        "UNION ALL SELECT id FROM @alpha WHERE title = 'x'"
    )
    requests = query_physical_source_requests(query)
    sources = tuple(resolve_source_request(name, facet=facet) for name, facet in requests)
    boundary = plan_source_boundaries(
        query,
        requests=requests,
        sources=sources,
        dates=DateContext(),
    )[0]

    assert not boundary.branch_empty
    assert boundary.eliminated_uses == 1
    assert boundary.required_fields == frozenset({"id", "title"})


def test_false_having_skips_single_source_acquisition() -> None:
    query = parse_query("SELECT uploader, COUNT(*) AS n FROM @example OF videos GROUP BY uploader HAVING 1 = 0")
    plan = plan_query(query, source=_source(), dates=DateContext())

    assert plan.source_branch_eliminated
    assert plan.acquisition.mode == "skip"
    assert plan.physical_request.required_fields == frozenset()
    assert plan.cost_class == "none"


def test_json_explain_reports_static_having_elimination_consistently() -> None:
    result = _run_cli(
        "--explain-format",
        "json",
        "--explain",
        "SELECT uploader, COUNT(*) AS n FROM @example GROUP BY uploader HAVING 1 = 0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["acquisition"]["strategy"] == "skip"
    assert payload["cost"]["class"] == "none"
    boundary = payload["source_boundaries"][0]
    assert boundary["branch_empty"] is True
    assert boundary["eliminated_uses"] == 1
    assert boundary["required_fields"] == []
    relation = boundary["relation_simplifications"][0]
    assert relation["empty"] is True
    assert relation["having_truth"] == "false"


def test_human_explain_reports_relation_simplification_reason() -> None:
    result = _run_cli(
        "--explain",
        "SELECT id FROM @example WHERE view_count >= 10 AND view_count < 10",
    )
    assert result.returncode == 0, result.stderr
    assert "Static relation simplification" in result.stdout
    assert "eliminated uses=1" in result.stdout
    assert "WHERE is proven never TRUE" in result.stdout
    assert "Strategy: skip" in result.stdout


def test_cli_static_empty_where_skips_source_acquisition(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "acquisition-called"
    fake = fake_bin / "yt-dlp"
    fake.write_text(
        """#!/bin/sh
if [ "$1" = "--version" ]; then
    printf '%s\\n' '2026.08.30'
    exit 0
fi
printf '%s\\n' 'called' > "$YT_DISCOVER_ACQUISITION_MARKER"
exit 99
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["YT_DISCOVER_ACQUISITION_MARKER"] = str(marker)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "-v",
            ("SELECT id FROM @example WHERE view_count >= 10 AND view_count < 10"),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not marker.exists()
    assert "Skipped source acquisition: static relation proofs" in result.stderr
