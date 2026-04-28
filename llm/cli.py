"""CLI entrypoint for the LLM processing MVP."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from llm.audit import build_status, scan_inputs
from llm.errors import ProviderError, safe_error_dict
from llm.pipeline import process_file
from llm.providers import build_provider, preflight_provider
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
    status.add_argument(
        "--run-id",
        default=None,
        help="Read a specific runs/<run-id>.jsonl file.",
    )

    preflight = subparsers.add_parser(
        "preflight",
        help="Check provider configuration without sending a live request by default.",
    )
    preflight.add_argument(
        "--provider",
        default=None,
        help="Provider name. Defaults to MY_FIRST_AGENT_LLM_PROVIDER or fake.",
    )
    preflight.add_argument("--model", default=None, help="Provider model name.")
    preflight.add_argument(
        "--live",
        action="store_true",
        help=(
            "Send a real provider request. This may consume quota; output is still "
            "redacted."
        ),
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
                build_status(
                    state_path=args.state_path,
                    runs_dir=args.runs_dir,
                    run_id=args.run_id,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "preflight":
        # preflight 默认只检查本地配置；--live 才触发真实请求，且输出必须红线脱敏。
        report = preflight_provider(
            args.provider,
            model=args.model,
            live=args.live,
        )
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0 if report["status"] == "ok" else 1

    try:
        provider = build_provider(args.provider, model=args.model)
    except ProviderError as exc:
        # 配置错误给机器可读错误，不让普通用户看到 traceback 或 secret。
        print(
            json.dumps(
                {"status": "error", "error": safe_error_dict(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    logger = RunLogger(state_path=args.state_path, runs_dir=args.runs_dir)
    result = process_file(args.input_file, provider=provider, logger=logger)
    output = {
        "run_id": result.run_id,
        "status": result.status,
        "input_file_hash": result.input_file_hash,
        "run_path": str(result.run_path),
    }
    if result.error:
        output["error"] = result.error
    print(
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.status == "ok" else 1
