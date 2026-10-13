from legacy_parser.cli import run
from legacy_parser.loader import load_line


def test_loader_and_cli_keep_record_behavior() -> None:
    expected = {"name": "Ada", "note": "hello"}

    assert load_line(" name=Ada ; note = hello ") == expected
    assert run(["name=Ada;note=hello"]) == expected
