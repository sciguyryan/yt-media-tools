"""Keep the representative formatter matrix aligned with Discover's parser."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
from yt_media_tools.query_parser import parse_query  # noqa: E402


class GrammarMatrixTests(unittest.TestCase):
    def test_representative_queries_remain_valid_ytsql(self) -> None:
        cases = json.loads((Path(__file__).with_name("syntax_matrix.json")).read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 15)
        for case in cases:
            with self.subTest(case=case["id"]):
                parse_query(case["query"])
