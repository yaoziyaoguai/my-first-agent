#!/usr/bin/env python3
"""Memory Proposal Anchor fake-mode dogfood runner.

中文学习边界：
这个脚本是 Memory Anchor fake-provider 的端到端狗粮验证——通过 core.chat()
完整路径证明 Memory Proposal Anchor 全链路正常，而非 harness 直接调用
dispatcher.route()。

DOGFOOD_PLAN.md §2.4 定义了 13 条 PASS 标准；本脚本使用共享检查模块
``_dogfood_memory_anchor_checks.py`` 执行 evidence 字段验证。

约束：
- 使用 FakeProvider（确定性、无外部调用）
- 不读 .env
- 不调真实 LLM/API
- 不读 memory/episodes/*.jsonl
- 不读真实 sessions/runs
- 不写 human_approved
- 不 auto approve
- 报告输出到 /private/tmp（不污染 repo）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# 确保项目根目录在 sys.path 中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# 共享检查模块（与 real smoke dogfood 复用同一套 PASS 标准）
from scripts._dogfood_memory_anchor_checks import (  # noqa: E402
    build_action_detail_lines,
    build_overclaim_prevention_section,
    check_memory_anchor_evidence,
)


def _build_fake_provider() -> Any:
    """构建确定性 FakeProvider——不读 .env，不调真实 API。"""
    from agent.provider.fake_provider import FakeProvider

    return FakeProvider()


def _build_phase1_dispatcher() -> Any:
    """构建 Phase 1 RuntimeActionDispatcher。"""
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    return build_phase1_dispatcher()


def _run_memory_anchor_fake_dogfood() -> dict[str, Any]:
    """执行一次 Memory Anchor fake-provider dogfood 并收集所有 evidence。

    走 core.chat() → run_main_loop → turn-end hook → dispatcher.route() 全链路。
    与 dogfood_e2e_runtime.py 的本质区别：不直接构造 RuntimeActionRequest，
    不冒充 real_core_loop_runtime_e2e。

    Returns:
        dict with: status, chat_result, action_count, actions, errors, pass_checks, fail_checks
    """
    from agent.core import chat

    provider = _build_fake_provider()
    dispatcher = _build_phase1_dispatcher()
    errors: list[str] = []

    # 调用 core.chat()——真实入口，不是 direct dispatch
    try:
        result = chat(
            "以后叫我小王",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        errors.append(f"chat() raised: {type(exc).__name__}: {exc}")
        return {
            "status": "FAIL",
            "chat_result": "",
            "action_count": 0,
            "actions": [],
            "errors": errors,
            "pass_checks": [],
            "fail_checks": ["chat_completed"],
        }

    # 收集 action_log 中每个 event 的完整 evidence（含 payload 级字段）
    action_log = list(dispatcher.action_log)
    actions = []
    for event in action_log:
        evidence = dict(event.evidence)
        actions.append({
            "action_id": event.action_id,
            "action_type": str(event.action_type),
            "source": event.source,
            "status": event.status,
            # evidence 分类字段
            "evidence_level": evidence.get("evidence_level", ""),
            "core_loop_invoked": evidence.get("core_loop_invoked"),
            "core_entrypoint": evidence.get("core_entrypoint"),
            "runtime_hook_name": evidence.get("runtime_hook_name"),
            "provider_kind": evidence.get("provider_kind"),
            "provider_external_call": evidence.get("provider_external_call"),
            "external_side_effects": evidence.get("external_side_effects"),
            # target module proof
            "target_module": evidence.get("target_module"),
            "target_module_proof_exists": evidence.get("target_module_proof") is not None,
            # handler payload 字段（在 evidence_extra 中展开）
            "disposition": evidence.get("disposition"),
            "pending_review": evidence.get("pending_review"),
            "auto_approved": evidence.get("auto_approved"),
            "not_confirmed": evidence.get("not_confirmed"),
            "real_episodes_read": evidence.get("real_episodes_read"),
            "secret_like_detected": evidence.get("secret_like_detected"),
            "no_silent_retain": evidence.get("no_silent_retain"),
        })

    # ── PASS 标准检查（使用共享检查模块） ──
    check_result = check_memory_anchor_evidence(
        actions,
        expected_provider_kind="fake",
        expected_provider_external_call=False,
        expected_external_side_effects=False,
        pre_existing_errors=errors,
    )

    pass_checks = check_result["pass_checks"]
    fail_checks = check_result["fail_checks"]
    errors = check_result["errors"]

    # C1: chat() 正常完成（本函数已在外层检查，非共享模块范围）
    pass_checks.insert(0, "chat_completed")

    # C13: errors 列表为空
    if not errors:
        pass_checks.append("no_errors")

    status = "PASS" if not fail_checks and not errors else "FAIL"
    return {
        "status": status,
        "chat_result": result[:200] if result else "",
        "action_count": len(actions),
        "actions": actions,
        "errors": errors,
        "pass_checks": pass_checks,
        "fail_checks": fail_checks,
    }


def _build_report(report: dict[str, Any]) -> str:
    """生成人类可读 dogfood 报告。

    报告明确标注已验证和未验证项，避免 overclaim（DOGFOOD_PLAN.md §6）。
    使用共享检查模块的 build_action_detail_lines 和 build_overclaim_prevention_section。
    """
    lines = [
        "=" * 60,
        "Memory Proposal Anchor Fake-Mode Dogfood Report",
        "=" * 60,
        "",
        f"Status: {report['status']}",
        f"Chat result preview: {report['chat_result']}",
        f"RuntimeActions triggered: {report['action_count']}",
        "",
    ]

    # PASS/FAIL checks summary
    if report["pass_checks"]:
        lines.append("PASS CHECKS:")
        for c in report["pass_checks"]:
            lines.append(f"  [x] {c}")
        lines.append("")

    if report["fail_checks"]:
        lines.append("FAIL CHECKS:")
        for c in report["fail_checks"]:
            lines.append(f"  [ ] {c}")
        lines.append("")

    if report["errors"]:
        lines.append("ERRORS:")
        for err in report["errors"]:
            lines.append(f"  - {err}")
        lines.append("")

    # Per-event details（共享格式化逻辑）
    lines.extend(build_action_detail_lines(report["actions"]))

    # Overclaim prevention（共享声明）
    lines.append(build_overclaim_prevention_section())
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"Result: {report['status']}")
    lines.append("=" * 60)

    return "\n".join(lines)


def main() -> int:
    """运行 Memory Anchor fake-mode dogfood 并输出报告。"""
    report_path = os.environ.get(
        "PHASE1_REPORT_PATH",
        "/private/tmp/phase1_memory_anchor_dogfood_report.txt",
    )

    print("Memory Proposal Anchor Fake-Mode Dogfood", flush=True)
    print(f"Report: {report_path}", flush=True)
    print(f"Temp HOME: {os.environ.get('HOME', 'default')}", flush=True)
    print(flush=True)

    report = _run_memory_anchor_fake_dogfood()

    report_text = _build_report(report)
    print(report_text, flush=True)

    # 写文本报告
    with open(report_path, "w") as f:
        f.write(report_text)

    # 写 JSON 报告（含完整 action_log 展开 payload 字段）
    json_path = report_path.replace(".txt", ".json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nJSON report: {json_path}", flush=True)

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
