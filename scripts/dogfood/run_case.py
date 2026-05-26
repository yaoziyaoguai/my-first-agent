"""Dogfood harness: run a single real-API case via main.py and capture output.

用法:
    python scripts/dogfood/run_case.py \
        --case-id A1 \
        --home /tmp/dogfood_home \
        --timeout 60 \
        --inputs "你好" "y"

每个 --inputs 参数按顺序发送到 main.py 的 stdin，之间等待模型响应完成。
输出保存到 docs/dogfood/outputs/<case_id>.txt。
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_PY = PROJECT_ROOT / "main.py"
OUTPUT_DIR = PROJECT_ROOT / "docs" / "dogfood" / "outputs"


def _read_available(fd, timeout: float = 2.0) -> bytes:
    """读取 fd 上当前可用的所有数据，不无限阻塞。"""
    import select

    chunks = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.1)
        if r:
            try:
                chunk = os.read(fd.fileno(), 4096)
            except (OSError, ValueError):
                break
            if not chunk:
                break
            chunks.append(chunk)
            deadline = time.monotonic() + timeout
        else:
            break
    return b"".join(chunks)


def run_case(
    case_id: str,
    inputs: list[str],
    home: str,
    timeout: int,
) -> tuple[int, str, float]:
    """运行单个 case，返回 (exit_code, output, elapsed_seconds)。"""
    home_path = Path(home)
    home_path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_path)
    for k in (
        "MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE",
        "MY_FIRST_AGENT_RUN_REAL_LLM_E2E",
    ):
        env.pop(k, None)

    proc = subprocess.Popen(
        [sys.executable, str(MAIN_PY)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(PROJECT_ROOT),
        bufsize=0,
    )

    all_output = b""
    start_time = time.monotonic()

    try:
        for i, user_input in enumerate(inputs):
            if i == 0:
                pre_output = _read_available(proc.stdout, timeout=min(timeout, 15))
                all_output += pre_output
            else:
                pre_output = _read_available(proc.stdout, timeout=min(timeout, 60))
                all_output += pre_output

            line = (user_input + "\n").encode("utf-8")
            proc.stdin.write(line)
            proc.stdin.flush()

            time.sleep(0.5)
            post_output = _read_available(proc.stdout, timeout=min(timeout, 90))
            all_output += post_output

        time.sleep(1)
        final_output = _read_available(proc.stdout, timeout=5)
        all_output += final_output

        try:
            proc.stdin.write(b"/exit\n")
            proc.stdin.flush()
        except (OSError, BrokenPipeError):
            pass

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)

    except BrokenPipeError:
        pass
    except Exception:
        with contextlib.suppress(Exception):
            proc.kill()
    finally:
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=3)

    elapsed = time.monotonic() - start_time
    return proc.returncode, all_output.decode("utf-8", errors="replace"), elapsed


def sanitize_output(output: str) -> str:
    """移除可能泄露的 API key 片段。"""
    import re

    output = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "sk-***REDACTED***", output)
    return output


def main():
    parser = argparse.ArgumentParser(description="Dogfood case runner")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--home", default="/tmp/dogfood_home")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--inputs", nargs="*", default=[])
    parser.add_argument("--input-file", help="从文件读取输入，每行一个")
    args = parser.parse_args()

    inputs = list(args.inputs)
    if args.input_file:
        with open(args.input_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    inputs.append(line)

    if not inputs:
        print(f"[{args.case_id}] SKIPPED: no inputs")
        return

    home = os.path.join(args.home, f"case_{args.case_id}")
    if os.path.exists(home):
        shutil.rmtree(home, ignore_errors=True)

    print(f"[{args.case_id}] Running with {len(inputs)} input(s)...", flush=True)
    exit_code, output, elapsed = run_case(args.case_id, inputs, home, args.timeout)

    output = sanitize_output(output)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{args.case_id}.txt"
    out_path.write_text(output, encoding="utf-8")

    out_lines = output.strip().split("\n")
    summary_line = ""
    for line in out_lines:
        if "本轮运行摘要" in line or "run summary" in line.lower():
            summary_line = line.strip()
            break

    print(
        f"[{args.case_id}] exit={exit_code} elapsed={elapsed:.1f}s "
        f"output_len={len(output)} "
        f"summary={summary_line[:120] if summary_line else 'N/A'}",
        flush=True,
    )


if __name__ == "__main__":
    main()
