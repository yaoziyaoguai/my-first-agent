from __future__ import annotations

import argparse
import json

from .service import ExportService


def run(argv: list[str]) -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("rows_json")
    args = parser.parse_args(argv)
    rows = json.loads(args.rows_json)
    return ExportService().export(rows)
