#!/usr/bin/env python3
"""Phase 1 real core loop E2E dogfood runner.

中文学习边界：
这个脚本证明 RuntimeAction 可以源自 core.chat() → runtime loop 路径，
而不是 dogfood harness 直接调用 dispatcher.route()。

Phase 1 约束：
- 使用 FakeProvider（确定性、无外部调用）
- 不读 .env
- 不调真实 LLM
- 不执行真实工具
- 不读/写真实 sessions/runs/memory episodes
- 默认 report 写入 /tmp

与 dogfood_e2e_runtime.py 的区别：
- dogfood_e2e_runtime.py：直接构造 RuntimeActionRequest 并调用 dispatcher.route()
  证明 harness-level evidence chain（harness_runtime_e2e）
- 本脚本：通过 core.chat() 完整路径，证明 real core loop evidence chain
  （real_core_loop_runtime_e2e）
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
    """构建确定性 FakeProvider。"""
    from agent.provider.fake_provider import FakeProvider

    return FakeProvider()


def _build_phase1_dispatcher() -> Any:
    """构建 Phase 1 RuntimeActionDispatcher，供 chat() 注入和事后检查。"""
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher

    return build_phase1_dispatcher()


def _run_phase1_real_core_loop() -> dict[str, Any]:
    """执行一次 Phase 1 real core loop 对话并收集证据。

    Returns:
        dict with keys: status, chat_result, action_count, actions, errors
    """
    from agent.core import chat
    provider = _build_fake_provider()
    dispatcher = _build_phase1_dispatcher()
    errors: list[str] = []

    # 调用 core.chat() — 真实入口
    try:
        result = chat(
            "以后叫我小王",
            provider=provider,
            runtime_action_dispatcher=dispatcher,
        )
    except Exception as exc:
        errors.append(f"chat() raised: {type(exc).__name__}: {exc}")
        return {
            "status": "failed",
            "chat_result": "",
            "action_count": 0,
            "actions": [],
            "errors": errors,
        }

    # 检查 RuntimeAction 是否被触发
    action_log = list(dispatcher.action_log)
    actions = []
    for event in action_log:
        evidence = dict(event.evidence)
        actions.append({
            "action_id": event.action_id,
            "action_type": str(event.action_type),
            "status": event.status,
            "evidence_level": evidence.get("evidence_level", ""),
            "core_loop_invoked": evidence.get("core_loop_invoked"),
            "core_entrypoint": evidence.get("core_entrypoint"),
            "runtime_hook_name": evidence.get("runtime_hook_name"),
            "provider_kind": evidence.get("provider_kind"),
            "external_side_effects": evidence.get("external_side_effects"),
            "target_module": evidence.get("target_module"),
            "target_module_proof_exists": evidence.get("target_module_proof") is not None,
        })

    # 验证
    if not actions:
        errors.append("no RuntimeAction triggered from core loop — loop turn-end hook did not fire")

    for action in actions:
        if action["core_loop_invoked"] is not True:
            errors.append(
                f"action {action['action_id']}: core_loop_invoked is not True "
                f"(got {action['core_loop_invoked']}) — downgraded to harness_runtime_e2e"
            )
        if action["evidence_level"] != "real_core_loop_runtime_e2e":
            errors.append(
                f"action {action['action_id']}: evidence_level={action['evidence_level']} "
                f"(expected real_core_loop_runtime_e2e)"
            )
        if action["provider_kind"] != "fake":
            errors.append(
                f"action {action['action_id']}: provider_kind={action['provider_kind']} "
                f"(expected 'fake')"
            )
        if action["external_side_effects"] is not False:
            errors.append(
                f"action {action['action_id']}: external_side_effects={action['external_side_effects']} "
                f"(expected False)"
            )

    status = "passed" if not errors else "failed"
    return {
        "status": status,
        "chat_result": result[:200] if result else "",
        "action_count": len(actions),
        "actions": actions,
        "errors": errors,
    }


def _build_report(report: dict[str, Any]) -> str:
    """生成人类可读报告。"""
    lines = [
        "=" * 60,
        "Phase 1 Real Core Loop E2E Dogfood Report",
        "=" * 60,
        "",
        f"Status: {report['status'].upper()}",
        f"Chat result preview: {report['chat_result']}",
        f"RuntimeActions triggered: {report['action_count']}",
        "",
    ]

    if report["errors"]:
        lines.append("ERRORS:")
        for err in report["errors"]:
            lines.append(f"  - {err}")
        lines.append("")

    for i, action in enumerate(report["actions"], 1):
        lines.append(f"--- Action {i} ---")
        lines.append(f"  action_id: {action['action_id']}")
        lines.append(f"  action_type: {action['action_type']}")
        lines.append(f"  status: {action['status']}")
        lines.append(f"  evidence_level: {action['evidence_level']}")
        lines.append(f"  core_loop_invoked: {action['core_loop_invoked']}")
        lines.append(f"  core_entrypoint: {action['core_entrypoint']}")
        lines.append(f"  runtime_hook_name: {action['runtime_hook_name']}")
        lines.append(f"  provider_kind: {action['provider_kind']}")
        lines.append(f"  external_side_effects: {action['external_side_effects']}")
        lines.append(f"  target_module: {action['target_module']}")
        lines.append(f"  target_module_proof_exists: {action['target_module_proof_exists']}")
        lines.append("")

    lines.append("=" * 60)
    lines.append(f"Result: {'PASS' if report['status'] == 'passed' else 'FAIL'}")
    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> int:
    """运行 Phase 1 real core loop dogfood 并输出报告。"""
    # 报告输出到 /tmp，不写 repo docs
    report_path = os.environ.get(
        "PHASE1_REPORT_PATH",
        "/tmp/phase1_real_core_loop_dogfood_report.txt",
    )

    print("Phase 1 Real Core Loop E2E Dogfood", flush=True)
    print(f"Report: {report_path}", flush=True)
    print(f"Temp HOME: {os.environ.get('HOME', 'default')}", flush=True)
    print(flush=True)

    report = _run_phase1_real_core_loop()

    report_text = _build_report(report)
    print(report_text, flush=True)

    # 写报告到文件（默认 /tmp）
    with open(report_path, "w") as f:
        f.write(report_text)

    # 同时输出 JSON 到 stdout 供自动化解析
    json_path = report_path.replace(".txt", ".json")
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nJSON report: {json_path}", flush=True)

    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
