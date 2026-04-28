"""CLI entrypoint for the LLM processing MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm.pipeline import process_file
from llm.providers import build_provider
from run_logger import RunLogger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py process",
        description="Run the minimal LLM processing pipeline.",
    )
    parser.add_argument("input_file", type=Path)
    parser.add_argument(
        "--provider",
        default=None,
        help="LLM provider name. Defaults to MY_FIRST_AGENT_LLM_PROVIDER or fake.",
    )
    parser.add_argument("--model", default=None, help="Provider model name.")
    parser.add_argument(
        "--state-path",
        type=Path,
        default=Path("state.json"),
        help="Path for process state metadata.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Directory for per-run JSONL audit logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    provider = build_provider(args.provider, model=args.model)
    logger = RunLogger(state_path=args.state_path, runs_dir=args.runs_dir)
    result = process_file(args.input_file, provider=provider, logger=logger)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "status": result.status,
                "input_file_hash": result.input_file_hash,
                "run_path": str(result.run_path),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0
