"""Local dashboard and test browser for the YT-SQL portable conformance corpus.

Serves a single-page dashboard computed from the live repository tree, and can
execute individual approved cases through the permanent conformance runner on
request. This is a working aid, not an audit: it has no --check gate and its
output is never a source of approved expectations.

Usage:
    python yt-sql/coverage_dashboard.py [--port PORT] [--open]
    python yt-sql/coverage_dashboard.py --write PATH

The server binds to 127.0.0.1 only. Static export embeds the current data in
one self-contained HTML file; run controls are disabled there.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SQL_ROOT = Path(__file__).resolve().parent
ASSETS = SQL_ROOT / "dashboard"
# Explicit route table: every script or stylesheet referenced by index.html
# must be listed here, which the dashboard test suite checks for.
ASSET_ROUTES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
    "/egg.js": "egg.js",
}
CONTENT_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "egg.js": "text/javascript; charset=utf-8",
}
RUN_TIMEOUT_SECONDS = 180


# ---------------------------------------------------------------------------
# Data layer: everything is computed from the live tree on request.

# Plain-language definitions for the dashboard's composition tables. The corpus
# is navigable by category prefix, but the prefixes alone do not explain the
# scope of each family to a new reader.
CATEGORY_DESCRIPTIONS = {
    "aggregate": "Aggregation over grouped rows: COUNT, SUM, AVG, MIN and MAX, including empty inputs.",
    "function-conformance": "Behaviour of individual built-in functions: argument arity, typing, NULL propagation and Unicode handling.",
    "interaction": "Compositions of two or more language features, such as pagination combined with predicates or nested functions.",
    "negative": "Deliberately malformed queries that must be rejected with a specific diagnostic category.",
    "ordering": "ORDER BY behaviour, tied groups and pagination boundaries.",
    "scalar": "Scalar expression evaluation: arithmetic, CASE, nesting and NULL propagation outside aggregation.",
    "semantics": "Predicate and comparison semantics, principally the LIKE, ILIKE and MATCHES family and three-valued logic.",
    "smoke": "Minimal end-to-end queries that demonstrate the harness executes approved cases.",
    "statement": "Statement-level clauses: DISTINCT, UNION, GROUP BY, LIMIT and OFFSET.",
    "temporal": "Date and timestamp parsing, arithmetic and comparison.",
    "unicode": "Unicode-specific behaviour: case mapping, normalisation boundaries and code-point ordering.",
}

OUTCOME_DESCRIPTIONS = {
    "rows": "The query returns typed result rows.",
    "error:syntax": "The query is rejected as ungrammatical.",
    "error:type": "The query is rejected for an invalid operand or type combination.",
    "error:resolution": "The query is rejected for an unresolved or ambiguous name.",
    "error:evaluation": "The query is rejected for a language-level runtime evaluation error.",
    "error:unsupported": "The query uses a recognised but unsupported language construct.",
    "error:parameter": "The query has invalid or missing parameter bindings.",
    "provisional": "The case is declared but its expectation has not been admitted yet.",
}


def case_category(identifier: str) -> str:
    """Return the category prefix of a case id, unwrapping torture mirrors."""
    return identifier.split(".", 2)[1] if identifier.startswith("torture.") else identifier.split(".")[0]


def _read_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_corpus() -> dict[str, object]:
    """Walk every declared case; structural failures are reported, not skipped."""
    cases: list[dict[str, object]] = []
    categories: dict[str, int] = {}
    outcomes: dict[str, int] = {}
    datasets: dict[str, int] = {}
    provisional = 0
    for path in sorted((SQL_ROOT / "cases").rglob("test.json")):
        manifest = _read_json(path)
        if not isinstance(manifest, dict):
            provisional += 1
            continue
        identifier = str(manifest.get("id", ""))
        if not identifier:
            provisional += 1
            continue
        expected = _read_json(path.parent / "expected.json")
        query = ""
        query_path = path.parent / "query.ysql"
        if query_path.is_file():
            query = query_path.read_text(encoding="utf-8").strip()
        case = {
            "id": identifier,
            "category": case_category(identifier),
            "path": str(path.parent.relative_to(SQL_ROOT / "cases")),
            "datasets": manifest.get("datasets", []),
            "features": manifest.get("features", []),
            "order": manifest.get("order", ""),
            "torture": identifier.startswith("torture."),
            "query": query,
            "provisional": expected is None,
        }
        if expected is None:
            case["outcome"] = "provisional"
        else:
            outcome = expected.get("outcome", "?")
            case["outcome"] = (
                outcome if outcome == "rows" else f"error:{expected.get('error', {}).get('category', '?')}"
            )
            case["columns"] = expected.get("columns", []) if outcome == "rows" else []
            case["row_count"] = len(expected.get("rows", [])) if outcome == "rows" else None
            case["error"] = expected.get("error", {}) if outcome != "rows" else {}
            case["expected"] = expected
        cases.append(case)
        # Composition counts describe the normative corpus only; torture mirrors
        # duplicate approved cases and are reported as their own total.
        if not case["torture"]:
            categories[str(case["category"])] = categories.get(str(case["category"]), 0) + 1
            outcomes[str(case["outcome"])] = outcomes.get(str(case["outcome"]), 0) + 1
            for dataset in case["datasets"]:
                datasets[str(dataset)] = datasets.get(str(dataset), 0) + 1
    return {
        "cases": cases,
        "categories": dict(sorted(categories.items())),
        "outcomes": dict(sorted(outcomes.items())),
        "datasets": dict(sorted(datasets.items())),
        "provisional": provisional,
    }


def load_audits() -> dict[str, object]:
    """Load the generated audits as committed; staleness is the standard chain's job."""
    gap_matrix = _read_json(SQL_ROOT / "COVERAGE-GAP-MATRIX.json") or {}
    retirement = _read_json(SQL_ROOT / "SEMANTIC-RETIREMENT-AUDIT.json") or {}
    reviewed = _read_json(SQL_ROOT / "REVIEWED-RETIREMENTS.json") or {}
    return {
        "gap_functions": gap_matrix.get("functions", []),
        "counts": retirement.get("counts", {}),
        "legacy_tests": retirement.get("legacy_tests", []),
        "reviewed_retirements": reviewed.get("retirements", []),
    }


def case_index(corpus: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(case["id"]): case for case in corpus["cases"]}  # type: ignore[index]


def overview_payload(corpus: dict[str, object], audits: dict[str, object]) -> dict[str, object]:
    cases = corpus["cases"]  # type: ignore[assignment]
    normative = sum(1 for case in cases if not case["torture"])  # type: ignore[union-attr,index]
    counts = audits["counts"]  # type: ignore[index]
    return {
        "normative_cases": normative,
        "torture_mirrors": len(cases) - normative,  # type: ignore[arg-type]
        "total_cases": len(cases),  # type: ignore[argtype]
        "provisional_cases": corpus["provisional"],  # type: ignore[index]
        "categories": corpus["categories"],  # type: ignore[index]
        "outcomes": corpus["outcomes"],  # type: ignore[index]
        "datasets": corpus["datasets"],  # type: ignore[index]
        "category_descriptions": CATEGORY_DESCRIPTIONS,
        "outcome_descriptions": OUTCOME_DESCRIPTIONS,
        "legacy_files": counts.get("legacy_test_files"),
        "legacy_test_functions": counts.get("test_functions"),
        "legacy_assertion_sites": counts.get("assertion_sites"),
        "reviewed_retirements": len(audits["reviewed_retirements"]),  # type: ignore[arg-type]
        "generated_note": "Legacy counts come from the committed SEMANTIC-RETIREMENT-AUDIT.json; "
        "rebuild the audit chain (inventory, gap matrix, audit) after tree changes.",
    }


def run_case(identifier: str) -> dict[str, object]:
    """Execute one approved case through the permanent conformance runner."""
    started = time.monotonic()
    process = subprocess.run(
        [sys.executable, str(SQL_ROOT / "run_conformance.py"), "--case", identifier, "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=RUN_TIMEOUT_SECONDS,
    )
    duration = round(time.monotonic() - started, 2)
    try:
        report = json.loads(process.stdout)
    except json.JSONDecodeError:
        return {"status": "infrastructure", "detail": process.stderr[-2000:], "duration_s": duration}
    results = report.get("results", [])
    if not results:
        return {"status": "setup_error", "detail": process.stderr[-2000:], "duration_s": duration}
    entry = results[0]
    entry["duration_s"] = duration
    entry["detail"] = entry.get("detail") or process.stdout[-500:]
    return entry


# ---------------------------------------------------------------------------
# HTTP layer.


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "YTSQLOverview/1"
    corpus: dict[str, object] = {}
    audits: dict[str, object] = {}

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass  # Keep the console quiet; failures still surface in responses.

    def _send(self, payload: object, status: int = 200, content_type: str = "application/json; charset=utf-8") -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        route = parsed.path
        if route == "/favicon.ico":
            # Browsers request this unprompted; serve an empty success rather
            # than a 404 that pollutes the console.
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif route in ASSET_ROUTES:
            self._serve_asset(ASSET_ROUTES[route])
        elif route == "/api/overview":
            self._send(overview_payload(self.corpus, self.audits))
        elif route == "/api/functions":
            self._send(self.audits["gap_functions"])  # type: ignore[index]
        elif route == "/api/legacy":
            self._send(
                {
                    "counts": self.audits["counts"],  # type: ignore[index]
                    "files": self.audits["legacy_tests"],  # type: ignore[index]
                    "reviewed_retirements": self.audits["reviewed_retirements"],  # type: ignore[index]
                }
            )
        elif route == "/api/cases":
            params = parse_qs(parsed.query)
            self._send(search_cases(params))
        elif route.startswith("/api/case/"):
            self._send(case_detail(route[len("/api/case/") :]))
        elif route == "/api/refresh":
            refresh_data()
            self._send({"status": "refreshed"})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        if route.startswith("/api/run/"):
            identifier = route[len("/api/run/") :]
            known = case_index(self.corpus).get(identifier)  # type: ignore[union-attr]
            if not isinstance(known, dict) or known.get("provisional"):
                self._send({"status": "unknown_case", "detail": "Only admitted cases can be executed."}, 404)
                return
            try:
                self._send(run_case(identifier))
            except subprocess.TimeoutExpired:
                self._send({"status": "timeout", "detail": f"Exceeded {RUN_TIMEOUT_SECONDS}s."}, 504)
        else:
            self._send({"error": "not found"}, 404)

    def _serve_asset(self, name: str) -> None:
        path = ASSETS / name
        if not path.is_file():
            self._send({"error": f"missing asset {name}"}, 500)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[name])
        self.send_header("Content-Length", str(len(body)))
        # The dashboard is in active development: never let the browser serve a
        # stale script, which would silently resurrect old behaviour.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def search_cases(params: dict[str, list[str]]) -> dict[str, object]:
    text = (params.get("q", [""])[0] or "").casefold()
    category = params.get("category", [""])[0]
    outcome = params.get("outcome", [""])[0]
    dataset = params.get("dataset", [""])[0]
    try:
        limit = max(1, min(int(params.get("limit", ["500"])[0]), 5000))
    except ValueError:
        limit = 500
    results = []
    for case in DashboardHandler.corpus["cases"]:  # type: ignore[index]
        if category and case["category"] != category:  # type: ignore[union-attr]
            continue
        if outcome and case["outcome"] != outcome:  # type: ignore[union-attr]
            continue
        if dataset and dataset not in case["datasets"]:  # type: ignore[union-attr]
            continue
        if text and text not in json.dumps(case, ensure_ascii=False).casefold():
            continue
        summary = {
            key: case[key]
            for key in ("id", "category", "path", "outcome", "datasets", "features", "torture", "provisional")
        }
        results.append(summary)
        if len(results) >= limit:
            break
    return {"matches": len(results), "truncated": len(results) >= limit, "cases": results}


def case_detail(identifier: str) -> object:
    case = case_index(DashboardHandler.corpus).get(identifier)  # type: ignore[arg-type,union-attr]
    if not isinstance(case, dict):
        return {"error": "unknown case"}
    return case


def refresh_data() -> None:
    DashboardHandler.corpus = load_corpus()
    DashboardHandler.audits = load_audits()


# ---------------------------------------------------------------------------
# Static export: one self-contained HTML file with embedded data.


def write_static(destination: Path) -> None:
    corpus, audits = load_corpus(), load_audits()
    payload = {
        "static": True,
        "overview": overview_payload(corpus, audits),
        "functions": audits["gap_functions"],  # type: ignore[index]
        "legacy": {
            "counts": audits["counts"],  # type: ignore[index]
            "files": audits["legacy_tests"],  # type: ignore[index]
            "reviewed_retirements": audits["reviewed_retirements"],  # type: ignore[index]
        },
        "cases": [
            {
                key: case[key]
                for key in (
                    "id",
                    "category",
                    "path",
                    "outcome",
                    "datasets",
                    "features",
                    "torture",
                    "provisional",
                    "query",
                )
            }
            for case in corpus["cases"]  # type: ignore[index]
        ],
    }
    html = (ASSETS / "index.html").read_text(encoding="utf-8")
    # Inline every asset: static snapshots must open from file:// where
    # absolute references to the server's paths do not resolve.
    html = html.replace(
        '<link rel="stylesheet" href="/style.css">',
        "<style>" + (ASSETS / "style.css").read_text(encoding="utf-8") + "</style>",
    )
    for name in ("app.js", "egg.js"):
        html = html.replace(
            f'<script src="/{name}"></script>',
            "<script>" + (ASSETS / name).read_text(encoding="utf-8") + "</script>",
        )
    html = html.replace(
        "</body>",
        "<script>window.__STATIC_DATA__ = " + json.dumps(payload, ensure_ascii=False) + ";</script></body>",
    )
    destination.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    parser.add_argument("--write", type=Path, metavar="PATH", help="Write a static snapshot instead of serving")
    args = parser.parse_args()
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        write_static(args.write)
        print(f"Wrote static dashboard: {args.write}")
        return 0
    refresh_data()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Serving YT-SQL dashboard on {url} (Ctrl+C to stop)")
    if args.open:
        import webbrowser

        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
