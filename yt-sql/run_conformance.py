"""Run approved portable expectations against a selected implementation adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from compare_outcomes import outcomes_match
from validate_corpus import ROOT, CorpusError, _load, validate_corpus


class HarnessError(ValueError):
    """Invalid harness configuration or normative corpus."""


def run(*, root: Path = ROOT, implementation: str = "python", configuration: str = "default") -> dict[str, object]:
    """Compare actual observations with committed expectations, never candidates."""
    if implementation != "python":
        raise HarnessError(f"no execution adapter registered for {implementation!r}")
    # Import lazily so corpus validation does not depend on an implementation.
    from run_python_candidate import observe

    validate_corpus(root)
    overrides = _load(root / "expectations" / f"{implementation}.json")["expectations"]
    results: list[dict[str, str]] = []
    for path in sorted((root / "cases").rglob("test.json")):
        case = path.parent
        manifest = _load(path)
        case_id = manifest["id"]
        try:
            expected = _load(case / "expected.json")
            actual = observe(case, configuration=configuration, root=root)
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
    args = parser.parse_args()
    try:
        report = run(root=args.root, implementation=args.implementation, configuration=args.configuration)
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
