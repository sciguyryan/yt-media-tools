#!/usr/bin/env python3
"""Run and present the yt-discover performance benchmark suite."""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class BenchmarkTarget:
    """Describe one public benchmark target and its underlying pytest node."""

    name: str
    node: str
    group: str
    description: str
    kind: str = "timing"


TARGETS = (
    BenchmarkTarget(
        "parser.simple",
        "benchmarks/test_query_pipeline_benchmarks.py::test_parse_query[simple]",
        "parser",
        "Parse a simple yt-sql query.",
    ),
    BenchmarkTarget(
        "parser.complex",
        "benchmarks/test_query_pipeline_benchmarks.py::test_parse_query[complex]",
        "parser",
        "Parse a representative complex yt-sql query.",
    ),
    BenchmarkTarget(
        "parser.collection",
        "benchmarks/test_query_pipeline_benchmarks.py::test_parse_query[collection]",
        "parser",
        "Parse a collection-heavy yt-sql query.",
    ),
    BenchmarkTarget(
        "resolution.simple",
        "benchmarks/test_query_pipeline_benchmarks.py::test_resolve_query[simple]",
        "resolution",
        "Resolve a simple parsed query.",
    ),
    BenchmarkTarget(
        "resolution.complex",
        "benchmarks/test_query_pipeline_benchmarks.py::test_resolve_query[complex]",
        "resolution",
        "Resolve a representative complex query.",
    ),
    BenchmarkTarget(
        "resolution.collection",
        "benchmarks/test_query_pipeline_benchmarks.py::test_resolve_query[collection]",
        "resolution",
        "Resolve a collection-heavy query.",
    ),
    BenchmarkTarget(
        "analysis.complex",
        "benchmarks/test_query_pipeline_benchmarks.py::test_analyse_complex_query",
        "analysis",
        "Analyse semantic properties of a representative complex query.",
    ),
    BenchmarkTarget(
        "optimiser.complex",
        "benchmarks/test_query_pipeline_benchmarks.py::test_optimise_complex_query",
        "optimiser",
        "Optimise a representative resolved query.",
    ),
    BenchmarkTarget(
        "evaluation.scalar.medium",
        "benchmarks/test_query_pipeline_benchmarks.py::test_evaluate_scalar_expression",
        "evaluation",
        "Evaluate a scalar expression over the normal deterministic record set.",
    ),
    BenchmarkTarget(
        "evaluation.collection.filter_map.medium",
        "benchmarks/test_query_pipeline_benchmarks.py::test_evaluate_collection_pipeline",
        "evaluation",
        "Evaluate a composed FILTER/MAP collection pipeline.",
    ),
    BenchmarkTarget(
        "end_to_end.offline.medium",
        "benchmarks/test_query_pipeline_benchmarks.py::test_apply_resolved_query",
        "end_to_end",
        "Execute a resolved query over deterministic local records.",
    ),
    BenchmarkTarget(
        "formatting.complex",
        "benchmarks/test_query_pipeline_benchmarks.py::test_format_complex_query",
        "formatting",
        "Format a representative resolved query.",
    ),
    BenchmarkTarget(
        "planning.acquisition.bounded",
        "benchmarks/test_query_pipeline_benchmarks.py::test_plan_acquisition",
        "planning",
        "Plan bounded acquisition without remote work.",
    ),
    BenchmarkTarget(
        "relational.join.one_to_one",
        "benchmarks/test_relational_benchmarks.py::test_inner_equality_join[one-to-one]",
        "relational",
        "Execute a one-to-one equality INNER JOIN.",
    ),
    BenchmarkTarget(
        "relational.join.one_to_many",
        "benchmarks/test_relational_benchmarks.py::test_inner_equality_join[one-to-many]",
        "relational",
        "Execute a one-to-many equality INNER JOIN.",
    ),
    BenchmarkTarget(
        "relational.join.no_match",
        "benchmarks/test_relational_benchmarks.py::test_inner_equality_join[no-match]",
        "relational",
        "Execute an equality INNER JOIN with no matches.",
    ),
    BenchmarkTarget(
        "relational.join.asymmetric.left_large",
        "benchmarks/test_relational_benchmarks.py::test_inner_equality_join[left-large]",
        "relational",
        "Execute an equality INNER JOIN with a much larger left relation.",
    ),
    BenchmarkTarget(
        "relational.join.asymmetric.right_large",
        "benchmarks/test_relational_benchmarks.py::test_inner_equality_join[right-large]",
        "relational",
        "Execute an equality INNER JOIN with a much larger right relation.",
    ),
    BenchmarkTarget(
        "relational.join.compound_equality",
        "benchmarks/test_relational_benchmarks.py::test_inner_compound_equality_join",
        "relational",
        "Execute a compound equality INNER JOIN.",
    ),
    BenchmarkTarget(
        "relational.join.semi",
        "benchmarks/test_relational_benchmarks.py::test_semi_equality_join",
        "relational",
        "Execute an equality SEMI JOIN.",
    ),
    BenchmarkTarget(
        "relational.planning.join_acquisition",
        "benchmarks/test_relational_benchmarks.py::test_join_acquisition_planning",
        "relational",
        "Plan and explain a JOIN with relation-owned acquisition requirements.",
    ),
    BenchmarkTarget(
        "cache.lookup.1",
        "benchmarks/test_cache_benchmarks.py::test_cache_lookup_known_ids[1]",
        "cache",
        "Look up one known metadata-cache key.",
    ),
    BenchmarkTarget(
        "cache.lookup.100",
        "benchmarks/test_cache_benchmarks.py::test_cache_lookup_known_ids[100]",
        "cache",
        "Look up 100 known metadata-cache keys.",
    ),
    BenchmarkTarget(
        "cache.lookup.1000",
        "benchmarks/test_cache_benchmarks.py::test_cache_lookup_known_ids[1000]",
        "cache",
        "Look up 1,000 known metadata-cache keys.",
    ),
    BenchmarkTarget(
        "analysis.ast_depth.8",
        "benchmarks/test_scaling_benchmarks.py::test_analysis_ast_depth[8]",
        "scaling",
        "Analyse an expression tree with depth 8.",
        "scaling",
    ),
    BenchmarkTarget(
        "analysis.ast_depth.32",
        "benchmarks/test_scaling_benchmarks.py::test_analysis_ast_depth[32]",
        "scaling",
        "Analyse an expression tree with depth 32.",
        "scaling",
    ),
    BenchmarkTarget(
        "analysis.ast_depth.128",
        "benchmarks/test_scaling_benchmarks.py::test_analysis_ast_depth[128]",
        "scaling",
        "Analyse an expression tree with depth 128.",
        "scaling",
    ),
    BenchmarkTarget(
        "end_to_end.offline.100",
        "benchmarks/test_scaling_benchmarks.py::test_offline_dataset_scaling[100]",
        "scaling",
        "Execute an offline query over 100 generated records.",
        "scaling",
    ),
    BenchmarkTarget(
        "end_to_end.offline.1000",
        "benchmarks/test_scaling_benchmarks.py::test_offline_dataset_scaling[1000]",
        "scaling",
        "Execute an offline query over 1,000 generated records.",
        "scaling",
    ),
    BenchmarkTarget(
        "end_to_end.offline.10000",
        "benchmarks/test_scaling_benchmarks.py::test_offline_dataset_scaling[10000]",
        "scaling",
        "Execute an offline query over 10,000 generated records.",
        "scaling",
    ),
    BenchmarkTarget(
        "memory.collection_pipeline.depth_1",
        "benchmarks/test_memory_benchmarks.py::test_collection_pipeline_peak_allocations[1]",
        "memory",
        "Measure traced allocations for collection pipeline depth 1.",
        "memory",
    ),
    BenchmarkTarget(
        "memory.collection_pipeline.depth_2",
        "benchmarks/test_memory_benchmarks.py::test_collection_pipeline_peak_allocations[2]",
        "memory",
        "Measure traced allocations for collection pipeline depth 2.",
        "memory",
    ),
    BenchmarkTarget(
        "memory.collection_pipeline.depth_4",
        "benchmarks/test_memory_benchmarks.py::test_collection_pipeline_peak_allocations[4]",
        "memory",
        "Measure traced allocations for collection pipeline depth 4.",
        "memory",
    ),
    BenchmarkTarget(
        "memory.collection_pipeline.depth_8",
        "benchmarks/test_memory_benchmarks.py::test_collection_pipeline_peak_allocations[8]",
        "memory",
        "Measure traced allocations for collection pipeline depth 8.",
        "memory",
    ),
)
TARGET_BY_NAME = {target.name: target for target in TARGETS}
TARGET_BY_NODE = {target.node: target for target in TARGETS}
GROUPS = tuple(dict.fromkeys(target.group for target in TARGETS))
NORMAL_GROUPS = tuple(group for group in GROUPS if group not in {"scaling", "memory", "stress"})


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic yt-discover performance benchmarks by public name or group."
    )
    parser.add_argument(
        "targets", nargs="*", metavar="NAME", help="Benchmark names or groups. With no names, run the normal suite."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run the entire benchmark suite, including scaling, memory and stress benchmarks.",
    )
    parser.add_argument(
        "--list", action="store_true", help="List public benchmark groups and benchmark names without running them."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show descriptions when listing and additional statistics in result tables.",
    )
    parser.add_argument("--save-baseline", metavar="NAME", help="Save pytest-benchmark timing results under NAME.")
    parser.add_argument(
        "--compare",
        metavar="BASELINE",
        help="Compare timing results with a saved baseline name or benchmark JSON file.",
    )
    parser.add_argument(
        "--benchmark-json", metavar="PATH", help="Also retain the current pytest-benchmark JSON result at PATH."
    )
    parser.add_argument(
        "--smoke", action="store_true", help="Use minimal timing rounds for a functional benchmark smoke run."
    )
    parser.add_argument("--ascii", action="store_true", help="Use an ASCII table instead of Unicode box drawing.")
    parser.add_argument("--no-colour", action="store_true", help="Disable colour in benchmark result tables.")
    return parser


def _list_targets(verbose: bool) -> None:
    print("Benchmark groups:")
    for group in GROUPS:
        members = [target for target in TARGETS if target.group == group]
        kinds = ", ".join(dict.fromkeys(target.kind for target in members))
        print(f"  {group:<14} {len(members):>2} benchmark(s) [{kinds}]")
    print("\nBenchmarks:")
    for target in TARGETS:
        print(f"  {target.name:<44} {target.description}" if verbose else f"  {target.name}")


def _resolve(names: list[str], run_all: bool) -> list[BenchmarkTarget]:
    if run_all:
        if names:
            raise ValueError("--all cannot be combined with named benchmark targets")
        return list(TARGETS)
    if not names:
        names = list(NORMAL_GROUPS)
    selected: list[BenchmarkTarget] = []
    unknown: list[str] = []
    for name in names:
        if name in TARGET_BY_NAME:
            candidates = [TARGET_BY_NAME[name]]
        elif name in GROUPS:
            candidates = [target for target in TARGETS if target.group == name]
        else:
            unknown.append(name)
            continue
        for candidate in candidates:
            if candidate not in selected:
                selected.append(candidate)
    if unknown:
        choices = list(GROUPS) + list(TARGET_BY_NAME)
        details = []
        for name in unknown:
            suggestions = difflib.get_close_matches(name, choices, n=3, cutoff=0.45)
            suffix = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            details.append(f"Unknown benchmark target {name!r}.{suffix}")
        raise ValueError("\n".join(details))
    return selected


def _require_benchmark_dependencies() -> bool:
    missing = [name for name in ("pytest_benchmark", "rich") if importlib.util.find_spec(name) is None]
    if not missing:
        return True
    print("benchmark.py: error: benchmark dependencies are not installed.", file=sys.stderr)
    print("Install them with:", file=sys.stderr)
    print("\n    python -m pip install -r requirements-benchmark.txt\n", file=sys.stderr)
    print(f"Missing: {', '.join(missing)}", file=sys.stderr)
    return False


def _run_pytest(nodes: list[str], extra: list[str], *, capture: bool = False) -> tuple[int, str]:
    if not nodes:
        return 0, ""
    command = [sys.executable, "-m", "pytest", *nodes, *extra]
    completed = subprocess.run(command, cwd=ROOT, check=False, text=True, capture_output=capture)
    output = ""
    if capture:
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode:
            sys.stderr.write(output)
    return completed.returncode, output


def _find_baseline(value: str) -> Path:
    explicit = Path(value).expanduser()
    if explicit.is_file():
        return explicit
    matches = sorted((ROOT / ".benchmarks").glob(f"**/*_{value}.json"))
    if not matches:
        raise ValueError(f"saved benchmark baseline {value!r} was not found")
    if len(matches) > 1:
        paths = "\n  ".join(str(path.relative_to(ROOT)) for path in matches)
        raise ValueError(f"baseline name {value!r} is ambiguous:\n  {paths}")
    return matches[0]


def _load_benchmarks(path: Path) -> dict[str, dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)
    results: dict[str, dict[str, Any]] = {}
    for item in document.get("benchmarks", []):
        fullname = item.get("fullname") or item.get("name", "")
        node = fullname.replace("\\", "/")
        target = next((candidate for candidate in TARGETS if node.endswith(candidate.node)), None)
        if target is not None:
            results[target.name] = item
    return results


def _format_duration(seconds: float) -> str:
    if seconds < 1e-6:
        return f"{seconds * 1e9:.2f} ns"
    if seconds < 1e-3:
        return f"{seconds * 1e6:.2f} µs"
    if seconds < 1:
        return f"{seconds * 1e3:.2f} ms"
    return f"{seconds:.3f} s"


def _assessment(change: float) -> tuple[str, str]:
    if change <= -5:
        return "↓ Improved", "green"
    if change <= 5:
        return "✓ Neutral", "green"
    if change <= 10:
        return "△ Review", "yellow"
    if change <= 20:
        return "! Material", "yellow"
    if change <= 50:
        return "!! Significant", "red"
    return "!!! Severe", "bold red"


def _console(no_colour: bool):
    from rich.console import Console

    return Console(no_color=no_colour or bool(os.environ.get("NO_COLOR")), highlight=False)


def _table_box(ascii_only: bool):
    from rich import box

    return box.ASCII if ascii_only else box.ROUNDED


def _render_results(
    current_path: Path,
    selected: list[BenchmarkTarget],
    *,
    baseline_path: Path | None,
    verbose: bool,
    ascii_only: bool,
    no_colour: bool,
) -> None:
    from rich.table import Table
    from rich.text import Text

    current = _load_benchmarks(current_path)
    baseline = _load_benchmarks(baseline_path) if baseline_path else {}
    console = _console(no_colour)
    title = "Benchmark comparison" if baseline_path else "Benchmark results"
    caption = f"Baseline: {baseline_path.stem}" if baseline_path else None
    table = Table(title=title, caption=caption, box=_table_box(ascii_only), expand=False, show_lines=False)
    table.add_column("Benchmark", no_wrap=True, overflow="ellipsis", min_width=20)
    if baseline_path:
        table.add_column("Baseline", justify="right", no_wrap=True)
        table.add_column("Current", justify="right", no_wrap=True)
        table.add_column("Change", justify="right", no_wrap=True)
        table.add_column("Assessment", no_wrap=True)
    else:
        table.add_column("Median", justify="right", no_wrap=True)
        table.add_column("Minimum", justify="right", no_wrap=True)
        if verbose:
            table.add_column("Mean", justify="right", no_wrap=True)
            table.add_column("Std dev", justify="right", no_wrap=True)
        table.add_column("Rounds", justify="right", no_wrap=True)
    for target in selected:
        if target.kind == "memory" or target.name not in current:
            continue
        item = current[target.name]
        stats = item["stats"]
        if baseline_path:
            old = baseline.get(target.name)
            if old is None:
                table.add_row(target.name, "-", _format_duration(stats["median"]), "new", "New")
                continue
            old_median = old["stats"]["median"]
            change = ((stats["median"] / old_median) - 1.0) * 100.0 if old_median else 0.0
            assessment, style = _assessment(change)
            table.add_row(
                target.name,
                _format_duration(old_median),
                _format_duration(stats["median"]),
                f"{change:+.1f}%",
                Text(assessment, style=style),
            )
        else:
            row = [target.name, _format_duration(stats["median"]), _format_duration(stats["min"])]
            if verbose:
                row.extend((_format_duration(stats["mean"]), _format_duration(stats["stddev"])))
            row.append(str(stats["rounds"]))
            table.add_row(*row)
    console.print(table)
    if baseline_path:
        console.print(
            "[dim]Assessments are guidance from median timing changes. Confirm material changes with repeat measurements and consider absolute cost and scaling.[/dim]"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.list:
        _list_targets(args.verbose)
        return 0
    try:
        selected = _resolve(args.targets, args.all)
        baseline_path = _find_baseline(args.compare) if args.compare else None
    except ValueError as exc:
        print(f"benchmark.py: error: {exc}", file=sys.stderr)
        return 2
    timing_targets = [target for target in selected if target.kind in {"timing", "scaling", "stress"}]
    memory = [target.node for target in selected if target.kind == "memory"]
    if timing_targets and not _require_benchmark_dependencies():
        return 2
    if args.verbose:
        print("Selected benchmarks:")
        for target in selected:
            print(f"  {target.name}")
    with tempfile.TemporaryDirectory(prefix="yt-media-benchmark-") as temp_dir:
        current_json = (
            Path(args.benchmark_json).expanduser() if args.benchmark_json else Path(temp_dir) / "current.json"
        )
        timing_args = [
            "--benchmark-only",
            "-m",
            "scale or stress or not (scale or stress or memory)",
            f"--benchmark-json={current_json}",
        ]
        if args.smoke:
            timing_args.extend(["--benchmark-min-rounds=1", "--benchmark-max-time=0.05"])
        if args.save_baseline:
            timing_args.append(f"--benchmark-save={args.save_baseline}")
        status, _output = _run_pytest([target.node for target in timing_targets], timing_args, capture=True)
        if status:
            return status
        if timing_targets:
            _render_results(
                current_json,
                timing_targets,
                baseline_path=baseline_path,
                verbose=args.verbose,
                ascii_only=args.ascii,
                no_colour=args.no_colour,
            )
        if memory:
            if args.save_baseline:
                print(
                    "Note: --save-baseline applies to statistical timing benchmarks; memory results are reported separately."
                )
            memory_status, _ = _run_pytest(memory, ["-m", "memory"])
            if memory_status:
                return memory_status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
