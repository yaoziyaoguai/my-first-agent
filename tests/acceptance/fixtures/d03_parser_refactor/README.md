# Parser refactor fixture

`legacy_parser.loader.load_line` and `legacy_parser.cli.run` currently duplicate
the same record parser. Refactor that parser behind a reusable module while
preserving observable behavior and all pre-existing user work.

Run the visible tests with `python -m pytest -q`.
