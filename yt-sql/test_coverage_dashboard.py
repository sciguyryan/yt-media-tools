"""Data-layer checks for the coverage dashboard; no HTTP server is started."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from coverage_dashboard import load_audits, load_corpus, overview_payload, run_case, write_static


class CorpusDataTests(unittest.TestCase):
    def test_corpus_matches_declared_case_count(self) -> None:
        corpus = load_corpus()
        declared = sum(1 for _ in (Path(__file__).resolve().parent / "cases").rglob("test.json"))
        self.assertEqual(len(corpus["cases"]), declared)
        self.assertGreater(corpus["provisional"], -1)
        self.assertIn("semantics", corpus["categories"])

    def test_every_corpus_case_has_a_valid_outcome_shape(self) -> None:
        corpus = load_corpus()
        for case in corpus["cases"]:
            self.assertIn(case["outcome"][0:4], ("rows", "erro", "prov"))

    def test_overview_payload_reports_legacy_counts(self) -> None:
        corpus, audits = load_corpus(), load_audits()
        overview = overview_payload(corpus, audits)
        self.assertEqual(overview["total_cases"], len(corpus["cases"]))
        self.assertEqual(overview["normative_cases"], sum(1 for c in corpus["cases"] if not c["torture"]))
        self.assertEqual(overview["torture_mirrors"], sum(1 for c in corpus["cases"] if c["torture"]))
        self.assertGreater(overview["legacy_assertion_sites"], 0)

    def test_torture_mirrors_report_under_their_source_category(self) -> None:
        corpus = load_corpus()
        self.assertNotIn("torture", corpus["categories"])
        mirror = next(c for c in corpus["cases"] if c["torture"])
        source = next(c for c in corpus["cases"] if c["id"] == mirror["id"][len("torture.") :])
        self.assertEqual(mirror["category"], source["category"])

    def test_gap_matrix_covers_all_registered_functions(self) -> None:
        audits = load_audits()
        self.assertEqual(len(audits["gap_functions"]), 20)
        for function in audits["gap_functions"]:
            self.assertIn("valid_syntax", function["dimensions"])
            self.assertIn("semantics", function["dimensions"])

    def test_run_case_returns_report_for_approved_case(self) -> None:
        corpus = load_corpus()
        approved = next(c["id"] for c in corpus["cases"] if not c["torture"] and c["outcome"] == "rows")
        result = run_case(approved)
        self.assertIn(result["status"], {"pass", "xfail"})

    def test_static_export_is_self_contained(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "dashboard.html"
            write_static(destination)
            html = destination.read_text(encoding="utf-8")
            self.assertIn("__STATIC_DATA__", html)
            # Static snapshots must not reference server paths: they open from file://.
            self.assertNotIn('src="/', html)
            self.assertNotIn('href="/', html)
            payload = json.loads(html.split("window.__STATIC_DATA__ = ", 1)[1].rsplit(";</script>", 1)[0])
            self.assertGreater(len(payload["cases"]), 100)
            self.assertIn("overview", payload)

    def test_egg_blobs_match_their_plain_payloads(self) -> None:
        from build_dashboard_egg import BRIEFINGS, EGG_PATH, check

        self.assertTrue(check())
        # Each briefing must have its own readable source and its own blob,
        # keyed by its own incantation.
        dashboard = Path(__file__).resolve().parent / "dashboard"
        for payload_name, constant, _trigger in BRIEFINGS:
            self.assertTrue((dashboard / payload_name).is_file())
            egg_source = EGG_PATH.read_text(encoding="utf-8")
            self.assertIn(f'const {constant} = "', egg_source)

    def test_every_asset_referenced_by_the_page_is_served(self) -> None:
        """Regression: /egg.js was referenced but never routed, 404ing silently."""
        from coverage_dashboard import ASSETS, ASSET_ROUTES

        page = (ASSETS / "index.html").read_text(encoding="utf-8")
        referenced = re.findall(r'(?:src|href)="/([^"]+)"', page)
        self.assertTrue(referenced)
        for name in referenced:
            self.assertIn(f"/{name}", ASSET_ROUTES)
            self.assertTrue((ASSETS / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
