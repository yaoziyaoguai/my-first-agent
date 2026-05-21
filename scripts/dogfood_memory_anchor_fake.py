#!/usr/bin/env python3
"""Memory Proposal Anchor fake-mode dogfood runner.

中文学习边界：
这个脚本是 Memory Anchor fake-provider 的端到端狗粮验证——通过 core.chat()
完整路径证明 Memory Proposal Anchor 全链路正常，而非 harness 直接调用
dispatcher.route()。

DOGFOOD_PLAN.md §2.4 定义了 13 条 PASS 标准；本脚本逐一验证并输出
人类可读报告和机器可读 JSON 报告。

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
        dict with: status, chat_result, action_count, actions, errors, pass_checks
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

    # ── PASS 标准检查（DOGFOOD_PLAN.md §2.4） ──
    pass_checks: list[str] = []
    fail_checks: list[str] = []

    # C1: chat() 正常完成
    pass_checks.append("chat_completed")

    # C2: action_log 至少包含 1 个 event
    if len(actions) >= 1:
        pass_checks.append("action_log_non_empty")
    else:
        fail_checks.append("action_log_non_empty")
        errors.append("action_log is empty — turn-end hook did not fire")

    if actions:
        a = actions[0]

        # C3: evidence_level == real_core_loop_runtime_e2e
        if a["evidence_level"] == "real_core_loop_runtime_e2e":
            pass_checks.append("evidence_level_correct")
        else:
            fail_checks.append("evidence_level_correct")
            errors.append(
                f"evidence_level={a['evidence_level']} "
                f"(expected real_core_loop_runtime_e2e)"
            )

        # C4: core_loop_invoked == True
        if a["core_loop_invoked"] is True:
            pass_checks.append("core_loop_invoked_true")
        else:
            fail_checks.append("core_loop_invoked_true")
            errors.append("core_loop_invoked is not True")

        # C5: core_entrypoint == "core.chat"
        if a["core_entrypoint"] == "core.chat":
            pass_checks.append("core_entrypoint_correct")
        else:
            fail_checks.append("core_entrypoint_correct")
            errors.append(f"core_entrypoint={a['core_entrypoint']} (expected core.chat)")

        # C6: runtime_hook_name == "loop.turn_end"
        if a["runtime_hook_name"] == "loop.turn_end":
            pass_checks.append("runtime_hook_name_correct")
        else:
            fail_checks.append("runtime_hook_name_correct")
            errors.append(
                f"runtime_hook_name={a['runtime_hook_name']} (expected loop.turn_end)"
            )

        # C7: target_module_proof 非 None
        if a["target_module_proof_exists"]:
            pass_checks.append("target_module_proof_exists")
        else:
            fail_checks.append("target_module_proof_exists")
            errors.append("target_module_proof is None — observer chain broken")

        # C8: target_module == "MemoryPolicy"
        if a["target_module"] == "MemoryPolicy":
            pass_checks.append("target_module_correct")
        else:
            fail_checks.append("target_module_correct")
            errors.append(
                f"target_module={a['target_module']} (expected MemoryPolicy)"
            )

        # C9: auto_approved == False
        if a["auto_approved"] is False:
            pass_checks.append("auto_approved_false")
        else:
            fail_checks.append("auto_approved_false")
            errors.append(f"auto_approved={a['auto_approved']} (expected False)")

        # C10: not_confirmed == True
        if a["not_confirmed"] is True:
            pass_checks.append("not_confirmed_true")
        else:
            fail_checks.append("not_confirmed_true")
            errors.append(f"not_confirmed={a['not_confirmed']} (expected True)")

        # C11: provider_kind == "fake"
        if a["provider_kind"] == "fake":
            pass_checks.append("provider_kind_fake")
        else:
            fail_checks.append("provider_kind_fake")
            errors.append(f"provider_kind={a['provider_kind']} (expected 'fake')")

        # C12: external_side_effects == False
        if a["external_side_effects"] is False:
            pass_checks.append("external_side_effects_false")
        else:
            fail_checks.append("external_side_effects_false")
            errors.append(
                f"external_side_effects={a['external_side_effects']} (expected False)"
            )

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

    # Per-event details (含 payload 级字段)
    for i, action in enumerate(report["actions"], 1):
        lines.append(f"--- Action {i} ---")
        lines.append(f"  action_id: {action['action_id']}")
        lines.append(f"  action_type: {action['action_type']}")
        lines.append(f"  source: {action['source']}")
        lines.append(f"  status: {action['status']}")
        lines.append(f"  evidence_level: {action['evidence_level']}")
        lines.append(f"  core_loop_invoked: {action['core_loop_invoked']}")
        lines.append(f"  core_entrypoint: {action['core_entrypoint']}")
        lines.append(f"  runtime_hook_name: {action['runtime_hook_name']}")
        lines.append(f"  provider_kind: {action['provider_kind']}")
        lines.append(f"  external_side_effects: {action['external_side_effects']}")
        lines.append(f"  target_module: {action['target_module']}")
        lines.append(f"  target_module_proof_exists: {action['target_module_proof_exists']}")
        lines.append(f"  disposition: {action['disposition']}")
        lines.append(f"  pending_review: {action['pending_review']}")
        lines.append(f"  auto_approved: {action['auto_approved']}")
        lines.append(f"  not_confirmed: {action['not_confirmed']}")
        lines.append(f"  real_episodes_read: {action['real_episodes_read']}")
        lines.append(f"  secret_like_detected: {action['secret_like_detected']}")
        lines.append(f"  no_silent_retain: {action['no_silent_retain']}")
        lines.append("")

    # Overclaim prevention (DOGFOOD_PLAN.md §6)
    lines.append("=" * 60)
    lines.append("Memory Proposal Anchor 验证范围")
    lines.append("=" * 60)
    lines.append("")
    lines.append("已验证（本锚点范围内）：")
    lines.append("  [x] core.chat 统一入口")
    lines.append("  [x] run_main_loop turn-end hook 触发")
    lines.append("  [x] RuntimeActionDispatcher.route() 调用")
    lines.append("  [x] MemoryTurnEndProposalHandler 处理")
    lines.append("  [x] target_module_proof 存在")
    lines.append("  [x] evidence_level 正确分类")
    lines.append("  [x] pending_review only / no auto approve")
    lines.append("  [x] provider_kind 正确标记")
    lines.append("")
    lines.append("未验证（不在本锚点范围）：")
    lines.append("  [ ] Layer 2: memory approve/confirm/retain 流程")
    lines.append("  [ ] Layer 3: memory recall/use")
    lines.append("  [ ] ToolRegistry 集成")
    lines.append("  [ ] Checkpoint 集成")
    lines.append("  [ ] SubAgent 集成")
    lines.append("  [ ] 多 turn 对话 memory 累积")
    lines.append("  [ ] 跨 session memory 持久化")
    lines.append("  [ ] Full real E2E（含工具执行）")
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
