"""Execute a supported portable case with Python and write a provisional observation.

Unsupported case shapes fail explicitly; observations are never normative expectations.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal

from typed_values import _typed
from pathlib import Path

from compare_outcomes import _validate
from validate_corpus import _load, validate_case

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
sys.path.insert(0, str(PROJECT / "python"))  # noqa: E402


class AdapterError(ValueError):
    """A case or configuration cannot be faithfully executed by this adapter."""


def _portable(value: object) -> object:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return {"type": "integer", "value": str(value)}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise AdapterError("non-finite decimal result")
        return {"type": "decimal", "value": format(value, "f")}
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise AdapterError("naive datetime result")
        return {"type": "timestamp", "value": value.isoformat()}
    raise AdapterError(f"unsupported result value type: {type(value).__name__}")


def _bind_portable_parameters(query: str, parameters: dict[str, object]) -> str:
    """Bind portable scalar values as SQL literals without changing quoted text.

    Keep this separate from the CLI binder: that interface intentionally treats
    every supplied value as text and folds parameter names to lower case.
    """
    literals: dict[str, str] = {}
    for name, value in parameters.items():
        kind, native = _typed(value)
        if kind == "null":
            literals[name] = "NULL"
        elif kind == "boolean":
            literals[name] = "TRUE" if native else "FALSE"
        elif kind in {"integer", "decimal"}:
            literals[name] = str(native)
        elif kind == "text":
            literals[name] = "'" + native.replace("'", "''") + "'"
        elif kind == "timestamp":
            # The parser accepts ISO datetime tokens directly. Normalise to
            # UTC because the portable typed-value contract compares instants,
            # not their original offset spellings. Keep microsecond precision.
            literals[name] = native.isoformat(timespec="microseconds").replace("+00:00", "Z")
        else:
            raise AdapterError(f"portable parameter type is not yet supported: {kind}")

    result: list[str] = []
    used: set[str] = set()
    index = 0
    quote: str | None = None
    while index < len(query):
        char = query[index]
        if quote is not None:
            result.append(char)
            if char == quote:
                if index + 1 < len(query) and query[index + 1] == quote:
                    result.append(query[index + 1])
                    index += 2
                    continue
                quote = None
            elif char == "\\" and index + 1 < len(query):
                result.append(query[index + 1])
                index += 2
                continue
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            result.append(char)
            index += 1
            continue
        if (
            char == ":"
            and index + 1 < len(query)
            and (query[index + 1].isascii() and (query[index + 1].isalpha() or query[index + 1] == "_"))
        ):
            end = index + 2
            while end < len(query) and query[end].isascii() and (query[end].isalnum() or query[end] == "_"):
                end += 1
            name = query[index + 1 : end]
            if name not in literals:
                raise AdapterError(f"missing portable parameter binding: {name}")
            result.append(literals[name])
            used.add(name)
            index = end
            continue
        result.append(char)
        index += 1
    unused = sorted(set(literals) - used)
    if unused:
        raise AdapterError("unused portable parameter bindings: " + ", ".join(unused))
    return "".join(result)


def observe(case: Path, *, configuration: str = "default", root: Path = ROOT) -> dict[str, object]:
    """Execute a supported case using declared portable source bindings."""
    validate_case(case, root=root, allow_missing_expected=True)
    manifest = _load(case / "test.json")
    configurations = manifest.get("execution", {}).get("configurations", [{"id": "default", "settings": {}}])
    matches = [entry for entry in configurations if entry["id"] == configuration]
    if len(matches) != 1:
        raise AdapterError(f"undeclared execution configuration: {configuration}")
    settings = matches[0]["settings"]
    if len(manifest["datasets"]) != 1:
        raise AdapterError("multiple dataset binding is not yet supported by the Python adapter")
    dataset = _load(root / "datasets" / f"{manifest['datasets'][0]}.json")
    if dataset.get("kind") not in {"static", "source-topology", "facet-topology"} or not isinstance(
        dataset.get("records"), list
    ):
        raise AdapterError("only static, source-topology and facet-topology datasets are supported")
    records = [dict(record) for record in dataset["records"]]
    # Topology is authoritative. In particular, an empty facet remains a
    # declared binding rather than silently acquiring its parent source.
    if dataset["kind"] == "static":
        bindings = {("@yt_sql_fixture", None): list(range(len(records)))}
    else:
        bindings = {}
        for entry in dataset["sources"]:
            bindings[(entry["handle"], None)] = list(entry["record_indices"])
        if dataset["kind"] == "facet-topology":
            for entry in dataset["facets"]:
                bindings[(entry["source"], entry["name"])] = list(entry["record_indices"])

    # Import after the local Python package path has been established.
    from yt_media_tools.dates import DateContext  # noqa: PLC0415
    from yt_media_tools.query import apply_query, canonical_record_value, parse_query, resolve_query  # noqa: PLC0415
    from yt_media_tools.schema import QuerySchema  # noqa: PLC0415

    from yt_media_tools.query_model import QueryLexicalError, QuerySemanticError, QuerySyntaxError  # noqa: PLC0415
    from yt_media_tools.query_semantics import query_physical_source_requests  # noqa: PLC0415

    def classify_semantic(exc: QuerySemanticError) -> dict[str, object]:
        # Only explicitly assigned structural reasons are portable. Do not
        # infer a category from an exception message or its broad class.
        if exc.context.category == "semantic" and exc.context.reason in {
            "unknown-field",
            "unknown-relation-alias",
            "ambiguous-field",
        }:
            return _validate({"version": 1, "outcome": "error", "error": {"category": "resolution"}})
        if exc.context.category == "semantic" and exc.context.reason == "non-numeric-aggregate":
            return _validate({"version": 1, "outcome": "error", "error": {"category": "type"}})
        raise AdapterError(
            f"unclassified Python language diagnostic: {exc.context.category}/{exc.context.reason}"
        ) from exc

    try:
        query_text = (case / "query.sql").read_text(encoding="utf-8")
        query = parse_query(_bind_portable_parameters(query_text, manifest.get("parameters", {})))
    except QueryLexicalError:
        # Tokenisation failures have a stable portable syntax meaning.
        return _validate({"version": 1, "outcome": "error", "error": {"category": "syntax"}})
    except QuerySemanticError as exc:
        return classify_semantic(exc)
    except QuerySyntaxError as exc:
        # Semantic errors inherit QuerySyntaxError. Only the actual syntax
        # category is classified here; semantic failures require a reviewed
        # resolution/type/unsupported mapping, not an exception-name guess.
        if exc.context.category != "syntax":
            raise AdapterError(f"unclassified Python language diagnostic: {exc.context.category}") from exc
        return _validate({"version": 1, "outcome": "error", "error": {"category": "syntax"}})
    requests = query_physical_source_requests(query)
    if not requests:
        raise AdapterError("queries without a physical source binding are not yet supported")
    for request in requests:
        if request not in bindings:
            raise AdapterError(f"physical source/facet is not bound to the portable dataset: {request!r}")
    # The evaluator assumes a single physical request has already been scoped
    # by acquisition. For multiple requests it filters by both source and facet.
    if len(requests) == 1:
        execution_records = [records[i] for i in bindings[requests[0]]]
    else:
        execution_records = []
        for source, facet in requests:
            for i in bindings[(source, facet)]:
                record = dict(records[i])
                record["_yt_sql_source"] = source
                record["_yt_sql_source_facet"] = facet
                execution_records.append(record)
    source_schemas = {request: QuerySchema([records[i] for i in bindings[request]]) for request in requests}
    try:
        resolved = resolve_query(
            query,
            QuerySchema(execution_records),
            DateContext(
                now=datetime.fromisoformat(settings["clock"].replace("Z", "+00:00"))
                if "clock" in settings
                else datetime(2026, 9, 1, tzinfo=timezone.utc)
            ),
            source_schemas=source_schemas,
        )
    except QuerySemanticError as exc:
        return classify_semantic(exc)
    optimisation = settings.get("optimisation", "enabled")
    # The public evaluator accepts this flag, so it is passed rather than simulated.
    result = apply_query(execution_records, resolved, relational_optimisation=optimisation == "enabled")
    columns = [term.output_name for term in resolved.select]
    rows = [[_portable(canonical_record_value(row, term)) for term in resolved.select] for row in result]
    return _validate({"version": 1, "outcome": "rows", "columns": columns, "rows": rows})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--configuration", default="default")
    args = parser.parse_args()
    try:
        observed = observe(args.case, configuration=args.configuration)
        with args.destination.open("x", encoding="utf-8") as stream:
            json.dump(observed, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (AdapterError, ValueError, OSError) as exc:
        parser.exit(1, f"Python candidate execution failed: {exc}\n")
    print(f"Wrote provisional observation: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
