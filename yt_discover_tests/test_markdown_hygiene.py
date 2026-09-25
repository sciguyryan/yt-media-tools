"""Project Markdown source hygiene tests."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_files_do_not_contain_consecutive_blank_lines() -> None:
    offenders = []
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in {"node_modules", ".venv", ".git"} for part in path.parts):
            continue
        if "\n\n\n" in path.read_text(encoding="utf-8"):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
