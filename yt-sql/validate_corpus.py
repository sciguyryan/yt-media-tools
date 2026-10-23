"""Validate portable YT-SQL corpus layout and result shapes without an engine."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from diagnostics import DiagnosticError, validate_diagnostic
from execution_config import ExecutionConfigError, validate_execution
from parameters import ParameterError, validate_parameters
from typed_values import TypedValueError, validate_values

ROOT = Path(__file__).resolve().parent


class CorpusError(ValueError):
    """A corpus file violates the portable structural contract."""


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CorpusError(f"duplicate key {key!r}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise CorpusError(f"invalid numeric constant {value}")


def _load(path: Path) -> object:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (OSError, UnicodeError, ValueError) as exc:
        raise CorpusError(f"{path}: {exc}") from exc

    def check_unicode(item: object) -> None:
        if isinstance(item, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in item):
            raise CorpusError(f"{path}: invalid Unicode surrogate")
        if isinstance(item, list):
            for child in item:
                check_unicode(child)
        if isinstance(item, dict):
            for key, child in item.items():
                check_unicode(key)
                check_unicode(child)

    check_unicode(value)
    return value


def _object(value: object, required: set[str], allowed: set[str], where: str) -> dict:
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - allowed:
        raise CorpusError(f"{where}: invalid object fields")
    return value


def validate_case(directory: Path, *, root: Path = ROOT, allow_missing_expected: bool = False) -> str:
    manifest = _object(
        _load(directory / "test.json"),
        {"version", "id", "datasets", "query", "expected", "order"},
        {
            "version",
            "id",
            "datasets",
            "query",
            "expected",
            "order",
            "description",
            "parameters",
            "features",
            "execution",
            "group_sizes",
        },
        str(directory),
    )
    case_id = manifest["id"]
    if (
        (type(manifest["version"]) is not int or manifest["version"] != 1)
        or not isinstance(case_id, str)
        or re.fullmatch(r"[a-z][a-z0-9_.-]+", case_id) is None
        or manifest["query"] != "query.sql"
        or manifest["expected"] != "expected.json"
        or manifest["order"] not in ("ordered", "unordered", "tied")
    ):
        raise CorpusError(f"{directory}: invalid case identity or contract version")
    sizes = manifest.get("group_sizes")
    if (manifest["order"] == "tied") != (sizes is not None):
        raise CorpusError(f"{case_id}: tied ordering requires group_sizes; other modes forbid it")
    if sizes is not None and (not isinstance(sizes, list) or any(type(size) is not int or size <= 0 for size in sizes)):
        raise CorpusError(f"{case_id}: invalid tied-group partition")
    if (
        not isinstance(manifest["datasets"], list)
        or not manifest["datasets"]
        or any(not isinstance(x, str) or re.fullmatch(r"[a-z][a-z0-9-]*", x) is None for x in manifest["datasets"])
        or len(set(manifest["datasets"])) != len(manifest["datasets"])
    ):
        raise CorpusError(f"{case_id}: invalid dataset references")
    for dataset in manifest["datasets"]:
        if "/" in dataset or "\\" in dataset or dataset.startswith("."):
            raise CorpusError(f"{case_id}: unsafe dataset name")
        data = _load(root / "datasets" / f"{dataset}.json")
        if not isinstance(data, dict) or data.get("id") != dataset:
            raise CorpusError(f"{case_id}: unresolved dataset {dataset}")
    if "description" in manifest and (not isinstance(manifest["description"], str) or not manifest["description"]):
        raise CorpusError(f"{case_id}: invalid description")
    if "features" in manifest and (
        not isinstance(manifest["features"], list)
        or any(not isinstance(x, str) or not x for x in manifest["features"])
        or len(set(manifest["features"])) != len(manifest["features"])
    ):
        raise CorpusError(f"{case_id}: invalid feature references")
    if "execution" in manifest:
        try:
            validate_execution(manifest["execution"])
        except ExecutionConfigError as exc:
            raise CorpusError(f"{case_id}: {exc}") from exc
    if "parameters" in manifest:
        try:
            validate_parameters(manifest["parameters"])
        except ParameterError as exc:
            raise CorpusError(f"{case_id}: {exc}") from exc
    try:
        query = (directory / "query.sql").read_text(encoding="utf-8")
        if any(0xD800 <= ord(char) <= 0xDFFF for char in query):
            raise CorpusError(f"{case_id}: invalid Unicode surrogate in query")
        if not query.strip():
            raise CorpusError(f"{case_id}: empty query")
    except (OSError, UnicodeError) as exc:
        raise CorpusError(f"{case_id}: unreadable query: {exc}") from exc
    if allow_missing_expected and not (directory / "expected.json").exists():
        return case_id
    result = _object(
        _load(directory / "expected.json"),
        {"version", "outcome"},
        {"version", "outcome", "columns", "rows", "error"},
        case_id,
    )
    if type(result["version"]) is not int or result["version"] != 1:
        raise CorpusError(f"{case_id}: invalid expected-result version")
    if sizes is not None and result["outcome"] != "rows":
        raise CorpusError(f"{case_id}: tied ordering requires a rows outcome")
    if result["outcome"] == "rows":
        if (
            "error" in result
            or not isinstance(result.get("columns"), list)
            or not all(isinstance(x, str) for x in result["columns"])
            or not isinstance(result.get("rows"), list)
        ):
            raise CorpusError(f"{case_id}: invalid rows outcome")
        if sizes is not None and sum(sizes) != len(result["rows"]):
            raise CorpusError(f"{case_id}: tied-group sizes do not match expected rows")
        try:
            validate_values(result["rows"], len(result["columns"]))
        except TypedValueError as exc:
            raise CorpusError(f"{case_id}: {exc}") from exc
    elif result["outcome"] == "error":
        if "columns" in result or "rows" in result:
            raise CorpusError(f"{case_id}: error outcome cannot contain rows")
        try:
            validate_diagnostic(result.get("error"))
        except DiagnosticError as exc:
            raise CorpusError(f"{case_id}: {exc}") from exc
    else:
        raise CorpusError(f"{case_id}: unknown outcome")
    return case_id


def validate_corpus(root: Path = ROOT) -> int:
    paths = sorted((root / "cases").rglob("test.json"))
    if not paths:
        raise CorpusError("no corpus cases found")
    ids: set[str] = set()
    for path in paths:
        case_id = validate_case(path.parent, root=root)
        if case_id in ids:
            raise CorpusError(f"duplicate case ID: {case_id}")
        ids.add(case_id)
    for implementation in ("python", "rust"):
        overrides = _object(
            _load(root / "expectations" / f"{implementation}.json"),
            {"version", "expectations"},
            {"version", "expectations"},
            implementation,
        )
        if (type(overrides["version"]) is not int or overrides["version"] != 1) or not isinstance(
            overrides["expectations"], dict
        ):
            raise CorpusError(f"{implementation}: invalid override manifest")
        for case_id, override in overrides["expectations"].items():
            if case_id not in ids:
                raise CorpusError(f"{implementation}: unknown case ID {case_id}")
            entry = _object(override, {"status", "reason"}, {"status", "reason", "issue", "category"}, case_id)
            if (
                entry["status"] != "xfail"
                or not isinstance(entry["reason"], str)
                or not entry["reason"].strip()
                or ("issue" in entry and (not isinstance(entry["issue"], str) or not entry["issue"].strip()))
                or ("category" in entry and (not isinstance(entry["category"], str) or not entry["category"].strip()))
            ):
                raise CorpusError(f"{implementation}: invalid xfail entry {case_id}")
    return len(paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Corpus root")
    args = parser.parse_args()
    try:
        count = validate_corpus(args.root)
    except CorpusError as exc:
        parser.exit(1, f"{exc}\n")
    print(f"Validated {count} portable corpus case(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
