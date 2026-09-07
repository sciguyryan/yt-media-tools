import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_downloader():
    spec = importlib.util.spec_from_file_location(
        "yt_downloader_test",
        ROOT / "yt-download.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_args(**overrides):
    values = {
        "cookies": "/tmp/cookies.txt",
        "archive": "/tmp/archive.txt",
        "rate_limit": "20M",
        "resolution": 1440,
        "output": "/downloads",
        "profile_output": "%(title)s [%(id)s] [%(uploader)s].%(ext)s",
        "playlist_reverse": False,
        "batch_file": "/tmp/ids.txt",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_default_profile_has_formal_signature_and_output_template():
    module = load_downloader()
    profile = module.load_profile("default")
    assert profile["path"] == "/mnt/storage/Downloads/YouTube/"
    assert profile["output"] == "%(title)s [%(id)s] [%(uploader)s].%(ext)s"


def test_build_command_uses_profile_output_template():
    module = load_downloader()
    command = module.build_command(make_args(), ["abc123"])
    output_index = command.index("-o") + 1
    assert command[output_index] == (
        "/downloads/%(title)s [%(id)s] [%(uploader)s].%(ext)s"
    )


def test_arbitrary_positive_resolution_is_accepted():
    module = load_downloader()
    assert module.resolution("900") == 900


def test_stdin_marker_cannot_be_mixed_with_targets():
    module = load_downloader()
    args = argparse.Namespace(
        input_file=None,
        targets=["-", "abc123"],
        batch_file="/tmp/ids.txt",
    )
    targets, error = module.resolve_targets(args)
    assert targets == []
    assert "cannot be combined" in error


def test_single_existing_positional_file_becomes_batch_file(tmp_path):
    module = load_downloader()
    batch = tmp_path / "ids"
    batch.write_text("abc123\n")
    args = argparse.Namespace(
        input_file=None,
        targets=[str(batch)],
        batch_file="/tmp/default-ids.txt",
    )
    targets, error = module.resolve_targets(args)
    assert targets == []
    assert error is None
    assert args.batch_file == str(batch)


def test_completed_ids_ignores_malformed_single_field_lines(tmp_path):
    module = load_downloader()
    archive = tmp_path / "archive.txt"
    archive.write_text(
        "youtube abc\nmalformed\nyoutube def extra\n\n",
        encoding="utf-8",
    )

    assert module.completed_ids(archive) == {"abc", "extra"}


def test_remove_completed_ids_preserves_unrelated_bytes(tmp_path):
    module = load_downloader()
    batch = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"
    original = b"# note\nabc\r\ndef\n\nhttps://example.invalid/abc\n"

    batch.write_bytes(original)
    archive.write_text("youtube abc\n", encoding="utf-8")

    assert module.remove_completed_ids(batch, archive) == 1
    assert batch.read_bytes() == b"# note\ndef\n\nhttps://example.invalid/abc\n"


def test_remove_completed_ids_does_not_remove_url_containing_archived_id(tmp_path):
    module = load_downloader()
    batch = tmp_path / "ids.txt"
    archive = tmp_path / "archive.txt"

    batch.write_text("https://example.invalid/abc\nabc\n", encoding="utf-8")
    archive.write_text("youtube abc\n", encoding="utf-8")

    assert module.remove_completed_ids(batch, archive) == 1
    assert batch.read_text(encoding="utf-8") == "https://example.invalid/abc\n"


def test_remove_completed_ids_requires_file_backed_input():
    module = load_downloader()
    args = argparse.Namespace(remove_completed_ids=True)

    assert module.validate_remove_completed_ids(args, ["abc123"]) == (
        "--remove-completed-ids requires a batch or input file"
    )
