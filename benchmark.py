#!/usr/bin/env python3
"""Run the yt-discover performance benchmark suite through one stable entry point."""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

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
        help="Show benchmark descriptions with --list and the selected benchmark names before execution.",
    )
    parser.add_argument("--save-baseline", metavar="NAME", help="Save pytest-benchmark timing results under NAME.")
    parser.add_argument("--benchmark-json", metavar="PATH", help="Write pytest-benchmark timing results to PATH.")
    parser.add_argument(
        "--smoke", action="store_true", help="Use minimal timing rounds for a functional benchmark smoke run."
    )
    return parser


def _list_targets(verbose: bool) -> None:
    print("Benchmark groups:")
    for group in GROUPS:
        members = [target for target in TARGETS if target.group == group]
        kinds = ", ".join(dict.fromkeys(target.kind for target in members))
        print(f"  {group:<14} {len(members):>2} benchmark(s) [{kinds}]")
    print("\nBenchmarks:")
    for target in TARGETS:
        if verbose:
            print(f"  {target.name:<44} {target.description}")
        else:
            print(f"  {target.name}")


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


def _run_pytest(nodes: list[str], extra: list[str]) -> int:
    if not nodes:
        return 0
    command = [sys.executable, "-m", "pytest", *nodes, *extra]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.list:
        _list_targets(args.verbose)
        return 0
    try:
        selected = _resolve(args.targets, args.all)
    except ValueError as exc:
        print(f"benchmark.py: error: {exc}", file=sys.stderr)
        return 2
    if args.verbose:
        print("Selected benchmarks:")
        for target in selected:
            print(f"  {target.name}")
    timing = [target.node for target in selected if target.kind in {"timing", "scaling", "stress"}]
    memory = [target.node for target in selected if target.kind == "memory"]
    timing_args = ["--benchmark-only", "-m", "scale or stress or not (scale or stress or memory)"]
    if args.smoke:
        timing_args.extend(["--benchmark-min-rounds=1", "--benchmark-max-time=0.05"])
    if args.save_baseline:
        timing_args.append(f"--benchmark-save={args.save_baseline}")
    if args.benchmark_json:
        timing_args.append(f"--benchmark-json={args.benchmark_json}")
    timing_status = _run_pytest(timing, timing_args)
    if timing_status:
        return timing_status
    if memory:
        if args.save_baseline:
            print(
                "Note: --save-baseline applies to statistical timing benchmarks; memory results are reported separately."
            )
        memory_status = _run_pytest(memory, ["-m", "memory"])
        if memory_status:
            return memory_status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
