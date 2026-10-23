#!/usr/bin/env python3
"""Compatibility launcher for python/benchmark.py."""

from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "python"))
runpy.run_path(str(Path(__file__).resolve().parent / "python" / "benchmark.py"), run_name="__main__")
