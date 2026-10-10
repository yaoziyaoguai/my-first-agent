"""S2 会话生命周期有界诊断（2026-10-10 执行包 §5.4，接口冻结）。

同进程成对打开真实产品入口（main()），四种模式各 N 对，试图复现
CheckpointSecurityError 并记录资源收尾。不新增产品 loop；只允许 fake/
scripted provider；使用独立合成目录；超时非零退出。

用法：
  .venv/bin/python docs/handoffs/2026-10-10-reliable-daily-use/diagnose_session_lifecycle.py \
    --pairs 100 --seed 20261010 --max-seconds 600 --output-dir <dir>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

_ORIGINAL_BUILD_PROVIDER = None


MODES = (
    "M1_terminal_reopen",
    "M2_approval_boundary",
    "M3_stream_teardown",
    "M4_partial_open_failure",
)


def _seeded(base: Path, mode: str, cycle: int) -> Path:
    d = base / mode / f"cycle-{cycle:03d}"
    (d / "workspace").mkdir(parents=True, exist_ok=True)
    return d


def _fake_argv(d: Path) -> list[str]:
    return [
        "--workspace", str(d / "workspace"),
        "--state-root", str(d / "state"),
        "--provider", "fake",
    ]


def _run_session(argv, inputs, *, patch=None):
    """一个真实 main() 会话；patch 可在启动路径注入一次性受控失败。"""
    import main as entrypoint

    outputs: list[str] = []
    it = iter(inputs)
    sentinel = object()

    def input_fn(_prompt: str) -> str:
        nxt = next(it, sentinel)
        return "" if nxt is sentinel else str(nxt)

    restore = None
    if patch is not None:
        restore = patch(entrypoint)
    try:
        code = entrypoint.main(argv, input_fn=input_fn, write_fn=outputs.append)
        return code, "\n".join(outputs)
    finally:
        if restore is not None:
            restore()


def _goal_proposal_provider_class():
    """M2 用：一次 write 提案→（批准后）结束。来自真实 GoalDraftProposal 流。"""

    from agent.runtime.contracts import (
        EvidenceOracleKind,
        GoalDraftProposal,
        ModelResponse,
        ModelTextBlock,
        ModelToolCall,
        ProposedCriterion,
    )

    class Scripted:
        def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
            g = next(
                (
                    b
                    for m in reversed(context.messages)
                    for b in m.content
                    if isinstance(b, dict) and b.get("type") == "trusted_goal"
                ),
                None,
            )
            if g is None:
                return ModelResponse(
                    (),
                    control=GoalDraftProposal(
                        correlation_id="diag-p1",
                        user_outcome="diag note written",
                        beneficiary="user",
                        targets=("diag.txt",),
                        scope=("workspace",),
                        non_goals=(),
                        assumptions=(),
                        proposed_criteria=(
                            ProposedCriterion(
                                "criterion:diag",
                                "diag.txt has exact content",
                                oracle_kind=EvidenceOracleKind.FILESYSTEM_DIGEST,
                                artifact_path="diag.txt",
                            ),
                        ),
                        next_step="write then read back",
                        requires_public_web=False,
                        requires_local_process=False,
                    ),
                )
            text = "\n".join(
                str(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
                for m in context.messages
                for b in m.content
            )
            if "write-1" not in text:
                return ModelResponse(
                    (
                        ModelToolCall(
                            "write-1",
                            "write_file",
                            {"path": "diag.txt", "content": "diagnosis\n"},
                        ),
                    )
                )
            if "readback-1" not in text:
                return ModelResponse(
                    (ModelToolCall("readback-1", "read_file", {"path": "diag.txt"}),)
                )
            return ModelResponse((ModelTextBlock("diag done"),))

    return Scripted


def _streaming_fake_class():
    """M3 用：经真实 delta_observer 路径发流的 fake provider。"""

    from agent.runtime.contracts import ModelResponse, ModelTextBlock

    class Streaming:
        def generate(self, context, *, delta_observer=None):  # noqa: ANN001, ANN202
            chunks = ["streamed ", "sentence ", "one."]
            if delta_observer is not None:
                for chunk in chunks:
                    delta_observer.on_text_delta(chunk)
            return ModelResponse((ModelTextBlock("".join(chunks)),))

    return Streaming


def _operator_inputs(mode: str, first: bool) -> list[str]:
    if mode == "M1_terminal_reopen":
        return ["hello cycle", "/exit"] if first else ["round two", "/exit"]
    if mode == "M2_approval_boundary":
        return (
            ["Task: create diag.txt containing exactly 'diagnosis'.", "/exit"]
            if first
            else ["y", "y", "y", "", "", "", "/exit"]
        )
    if mode == "M3_stream_teardown":
        return ["stream please", "/exit"] if first else ["stream again", "/exit"]
    return ["probe", "/exit"] if first else ["retry open", "/exit"]


def _wait_marker(mode: str) -> str | None:
    if mode == "M2_approval_boundary":
        return "Approval required"
    return None


def _patch_partial_open(entrypoint):  # noqa: ANN001
    """M4：第二会话资源获得阶段注入一次受控失败（sandbox resources 构建器）。"""
    import agent.composition as composition_mod

    orig = composition_mod.build_sandbox_resources
    state = {"fired": False}

    def failing(*a, **k):  # noqa: ANN002, ANN003
        if not state["fired"]:
            state["fired"] = True
            raise OSError("controlled partial-open failure")
        return orig(*a, **k)

    composition_mod.build_sandbox_resources = failing
    import main as main_mod

    main_mod.build_sandbox_resources = failing
    return lambda: (
        setattr(composition_mod, "build_sandbox_resources", orig),
        setattr(main_mod, "build_sandbox_resources", orig),
    )


def _checkpoint_intact(d: Path) -> bool:
    from agent.runtime.checkpoint import LocalCheckpointStore

    hits = list((d / "state" / "workspaces").rglob("*.json")) if (d / "state").exists() else []
    if not hits:
        return True  # 无 checkpoint 也算未损坏
    try:
        for hit in hits:
            LocalCheckpointStore(hit).load()
        return True
    except Exception:
        return False


def _fd_count() -> int:
    try:
        return len(os.listdir("/dev/fd"))
    except OSError:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--max-seconds", type=float, default=600.0)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.pairs < 1 or args.max_seconds <= 0:
        return 2

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)

    base = Path(
        __import__("tempfile").mkdtemp(prefix="fa-diag-", dir=ROOT / ".local")
    ).resolve()

    per_mode = max(1, args.pairs // len(MODES))
    deadline = time.monotonic() + args.max_seconds
    records: list[dict] = []
    timed_out = False
    fd0 = _fd_count()

    import main as entrypoint  # noqa: F401  单进程内复用同一产品模块
    global _ORIGINAL_BUILD_PROVIDER
    if _ORIGINAL_BUILD_PROVIDER is None:
        _ORIGINAL_BUILD_PROVIDER = entrypoint._build_provider

    for mode in MODES:
        for cycle in range(1, per_mode + 1):
            if time.monotonic() >= deadline:
                timed_out = True
                break
            d = _seeded(base, mode, cycle)
            rec = {
                "mode": mode,
                "cycle": cycle,
                "pid": os.getpid(),
            }
            try:
                import main as product_main

                if mode == "M2_approval_boundary":
                    cls = _goal_proposal_provider_class()
                    product_main._build_provider = lambda a, _c=cls: _c()
                elif mode == "M3_stream_teardown":
                    cls = _streaming_fake_class()
                    product_main._build_provider = lambda a, _c=cls: _c()
                else:
                    product_main._build_provider = _ORIGINAL_BUILD_PROVIDER
                argv = _fake_argv(d)
                c1, o1 = _run_session(
                    argv, _operator_inputs(mode, True)
                )
                rec["s1_exit"] = c1
                marker = _wait_marker(mode)
                if marker is not None and marker not in o1:
                    rec["note"] = f"marker {marker} not reached in S1"
                patch = _patch_partial_open if mode == "M4_partial_open_failure" else None
                c2, o2 = _run_session(
                    argv, _operator_inputs(mode, False), patch=patch
                )
                rec["s2_exit"] = c2
                if "CheckpointSecurityError" in o1 or "CheckpointSecurityError" in o2:
                    rec["reproduced"] = True
                    rec["detail"] = next(
                        line
                        for line in (o1 + "\n" + o2).splitlines()
                        if "CheckpointSecurityError" in line
                    )
                else:
                    rec["reproduced"] = False
                if mode == "M2_approval_boundary":
                    # S1 未批准不写；由 checkpoint 终态与文件共同断言
                    rec["diag_written"] = (d / "workspace" / "diag.txt").exists()
                if mode == "M4_partial_open_failure":
                    # 注入失败已消耗（一次性 flag）：第三次会话应能成功重开。
                    c3, o3 = _run_session(argv, ["after failure", "/exit"])
                    rec["s3_exit"] = c3
                rec["checkpoint_intact"] = _checkpoint_intact(d)
            except Exception as error:  # noqa: BLE001
                rec["harness_error"] = f"{type(error).__name__}: {error}"
            records.append(rec)
        if timed_out:
            break

    fd1 = _fd_count()
    summary = {
        "seed": args.seed,
        "pairs_requested": args.pairs,
        "pairs_executed": len(records),
        "per_mode": per_mode,
        "timed_out": timed_out,
        "reproduced_any": any(r.get("reproduced") for r in records),
        "reproduction_count": sum(1 for r in records if r.get("reproduced")),
        "harness_errors": sum(1 for r in records if "harness_error" in r),
        "checkpoint_damaged": sum(1 for r in records if r.get("checkpoint_intact") is False),
        "fd_delta": fd1 - fd0,
        "base_dir": str(base),
    }
    (out / "records.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8"
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if timed_out else 0


if __name__ == "__main__":
    raise SystemExit(main())
