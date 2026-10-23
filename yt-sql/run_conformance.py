"""Run approved portable expectations against a selected implementation adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare_outcomes import outcomes_match
from conformance_adapters import resolve
from validate_corpus import ROOT, CorpusError, _load, validate_corpus


class HarnessError(ValueError):
    """Invalid harness configuration or normative corpus."""


def run(
    *,
    root: Path = ROOT,
    implementation: str = "python",
    configuration: str = "default",
    case_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """Compare actual observations with committed expectations, never candidates."""
    try:
        observe = resolve(implementation)
    except ValueError as exc:
        raise HarnessError(str(exc)) from exc

    validate_corpus(root)
    overrides = _load(root / "expectations" / f"{implementation}.json")["expectations"]
    paths = sorted((root / "cases").rglob("test.json"))
    by_id = {_load(path)["id"]: path for path in paths}
    if case_ids is not None:
        if not case_ids:
            raise HarnessError("at least one case ID must be selected")
        unknown = sorted(set(case_ids) - by_id.keys())
        if unknown:
            raise HarnessError(f"unknown case ID(s): {', '.join(unknown)}")
        paths = [by_id[case_id] for case_id in sorted(set(case_ids))]
    results: list[dict[str, str]] = []
    for path in paths:
        case = path.parent
        manifest = _load(path)
        case_id = manifest["id"]
        try:
            expected = _load(case / "expected.json")
            actual = observe(case, configuration, root)
            matches = outcomes_match(expected, actual, order=manifest["order"])
            status = "pass" if matches else "fail"
            detail = "" if matches else "observed outcome differs from approved expectation"
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as exc:
            # An adapter crash is never an expected language error or an XFAIL.
            status = "error"
            detail = f"{type(exc).__name__}: {exc}"
        override = overrides.get(case_id)
        if override is not None and status != "error":
            if status == "pass":
                status = "xpass"
                detail = "unexpected pass of an implementation-specific XFAIL"
            elif override.get("category") == "outcome-mismatch":
                status = "xfail"
                detail = override["reason"]
            else:
                detail = "XFAIL mismatch category is not supported by this harness"
        results.append({"id": case_id, "status": status, "detail": detail})
    return {
        "version": 1,
        "implementation": implementation,
        "configuration": configuration,
        "results": results,
        "counts": {
            name: sum(r["status"] == name for r in results) for name in ("pass", "fail", "error", "xfail", "xpass")
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--implementation", default="python")
    parser.add_argument("--configuration", default="default")
    parser.add_argument("--json", action="store_true", help="Emit a deterministic machine-readable report")
    parser.add_argument(
        "--case", action="append", dest="cases", metavar="ID", help="Run an exact approved case ID (repeatable)"
    )
    parser.add_argument("--list-cases", action="store_true", help="List approved case IDs without executing adapters")
    args = parser.parse_args()
    try:
        if args.list_cases:
            validate_corpus(args.root)
            ids = sorted(_load(path)["id"] for path in (args.root / "cases").rglob("test.json"))
            print("\n".join(ids))
            return 0
        report = run(
            root=args.root,
            implementation=args.implementation,
            configuration=args.configuration,
            case_ids=tuple(args.cases) if args.cases is not None else None,
        )
    except (CorpusError, HarnessError, OSError, ValueError) as exc:
        parser.exit(2, f"Conformance setup failed: {exc}\n")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in report["results"]:
            print(f"{item['status'].upper():5} {item['id']}" + (f": {item['detail']}" if item["detail"] else ""))
        print(" ".join(f"{k}={v}" for k, v in report["counts"].items()))
    return 1 if any(report["counts"][name] for name in ("fail", "error", "xpass")) else 0


if __name__ == "__main__":
    raise SystemExit(main())
