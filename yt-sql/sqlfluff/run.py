"""Isolated SQLFluff entry point for the experimental YT-SQL dialect.

Usage: python yt-sql/sqlfluff/run.py lint --config .sqlfluff-ysql yt-sql/cases

The registry hook is private in SQLFluff 4.4.0. Fail on other versions until
compatibility has been explicitly reviewed rather than silently mis-linting.
"""

import sys
from pathlib import Path


def main() -> None:
    import sqlfluff
    from sqlfluff.core import dialects

    if sqlfluff.__version__ != "4.4.0":
        raise SystemExit("YT-SQL dialect integration requires SQLFluff 4.4.0")
    if not hasattr(dialects, "_dialect_lookup"):
        raise SystemExit("SQLFluff dialect registry is incompatible")

    # SQLFluff loads custom dialect modules through this internal registry.
    # Install a module alias, keeping all monkey-patching inside this process.
    import importlib.util

    module_path = Path(__file__).with_name("dialect_ytsql.py")
    spec = importlib.util.spec_from_file_location("sqlfluff.dialects.dialect_ytsql", module_path)
    if spec is None or spec.loader is None:
        raise SystemExit("Unable to load YT-SQL dialect")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    dialects._dialect_lookup["ytsql"] = ("dialect_ytsql", "ytsql_dialect")

    from sqlfluff.cli.commands import cli

    cli.main(args=sys.argv[1:], prog_name="sqlfluff-ysql", standalone_mode=True)


if __name__ == "__main__":
    main()
