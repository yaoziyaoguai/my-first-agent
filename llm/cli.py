"""CLI entrypoint for the LLM processing MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm.audit import build_status, scan_inputs
from llm.pipeline import process_file
from llm.providers import build_provider
from run_logger import RunLogger


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Run the minimal LLM processing commands.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    process = subparsers.add_parser(
        "process",
        help="Run the minimal triager/distiller/linker pipeline.",
    )
    process.add_argument("input_file", type=Path)
    process.add_argument(
        "--provider",
        default=None,
        help="LLM provider name. Defaults to MY_FIRST_AGENT_LLM_PROVIDER or fake.",
    )
    process.add_argument("--model", default=None, help="Provider model name.")
    process.add_argument(
        "--state-path",
        type=Path,
        default=Path("state.json"),
        help="Path for process state metadata.",
    )
    process.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Directory for per-run JSONL audit logs.",
    )

    scan = subparsers.add_parser(
        "scan",
        help="Scan input file or directory and print metadata only.",
    )
    scan.add_argument("target", type=Path)

    status = subparsers.add_parser(
        "status",
        help="Read state.json and runs/*.jsonl audit metadata.",
    )
    status.add_argument(
        "--state-path",
        type=Path,
        default=Path("state.json"),
        help="Path for process state metadata.",
    )
    status.add_argument(
        "--runs-dir",
        type=Path,
        default=Path("runs"),
        help="Directory for per-run JSONL audit logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "scan":
        # scan 是只读审计命令：只输出文件 metadata，不写 state/runs，不输出正文。
        entries = scan_inputs(args.target)
        print(
            json.dumps(
                {"inputs": [entry.__dict__ for entry in entries]},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "status":
        # status 只读 state/runs metadata；损坏日志转 warning，不把 raw text 打出来。
        print(
            json.dumps(
                build_status(state_path=args.state_path, runs_dir=args.runs_dir),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

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
