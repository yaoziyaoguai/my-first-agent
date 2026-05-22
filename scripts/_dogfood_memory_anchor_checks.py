"""Memory branch behavior dogfood 共享检查模块。

中文学习边界：
fake dogfood 和 real smoke dogfood 共享同一套核心 PASS 标准检查逻辑。
差异仅在于 provider 构造、授权门控和 expected metadata 值。
本模块提取共用的 evidence 字段断言，避免两套独立 PASS 标准漂移。

约束：
- 不接触 provider 对象
- 不读 .env
- 不打印 secret
- 只做 evidence 字段的结构化验证

架构依据：docs/plans/2026-05-22-001-feat-memory-anchor-real-smoke-plan.md
"""

from __future__ import annotations

from typing import Any


def find_memory_turn_end_action(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按 action_type 查找 memory.turn_end_proposal event。

    中文学习边界：
    dogfood report 只能检查 runtime 已产生的 evidence，不能把 action_log 顺序当
    架构契约。Memory 与 Tool gate 同属 turn-end lifecycle，未来顺序可能变化；
    checker 必须按 action_type 定位，避免 fake/real 报告逻辑分裂或误判。
    """
    for action in actions:
        if action.get("action_type") == "memory.turn_end_proposal":
            return action
    return None


def check_memory_anchor_evidence(
    actions: list[dict[str, Any]],
    *,
    expected_provider_kind: str,
    expected_provider_external_call: bool,
    expected_external_side_effects: bool,
    pre_existing_errors: list[str] | None = None,
) -> dict[str, Any]:
    """对 action_log 执行 Memory branch behavior PASS 标准检查。

    参数化 expected 值使得同一套检查逻辑可用于 fake/real 两种模式：
    - fake: provider_kind="fake", provider_external_call=False, external_side_effects=False
    - real smoke: provider_kind="real", provider_external_call=True, external_side_effects=False

    中文学习边界——为什么参数化而非两套函数：
    - fake/real 共享同一条 core.chat → run_main_loop → turn-end hook 路径
    - 唯一的差异是 provider metadata 的 expected 值
    - 参数化避免两套独立 PASS 标准漂移（review finding F5）

    Returns:
        dict with keys: pass_checks (list[str]), fail_checks (list[str]), errors (list[str])
    """
    errors: list[str] = list(pre_existing_errors or [])
    pass_checks: list[str] = []
    fail_checks: list[str] = []

    # C2: action_log 至少包含 1 个 event
    # C1 (chat completed) 由调用方在外层检查——本函数只检查 evidence 字段
    if len(actions) >= 1:
        pass_checks.append("action_log_non_empty")
    else:
        fail_checks.append("action_log_non_empty")
        errors.append("action_log is empty — turn-end hook did not fire")
        return {
            "pass_checks": pass_checks,
            "fail_checks": fail_checks,
            "errors": errors,
        }

    a = find_memory_turn_end_action(actions)
    if a is not None:
        pass_checks.append("memory_action_found")
    else:
        fail_checks.append("memory_action_found")
        errors.append(
            "memory.turn_end_proposal event not found in action_log — "
            "MEMORY action 可能未被 turn-end hook 发送或被 handler 拒绝"
        )
        return {
            "pass_checks": pass_checks,
            "fail_checks": fail_checks,
            "errors": errors,
        }

    # C3: evidence_level == real_core_loop_runtime_e2e
    # 这证明 event 确实来自 core loop 路径，不是 direct dispatcher
    if a.get("evidence_level") == "real_core_loop_runtime_e2e":
        pass_checks.append("evidence_level_correct")
    else:
        fail_checks.append("evidence_level_correct")
        errors.append(
            f"evidence_level={a.get('evidence_level')!r} "
            f"(expected real_core_loop_runtime_e2e)"
        )

    # C4: core_loop_invoked == True
    # 这是 loop.py turn-end hook 注入的标志——缺此字段意味着 hook 未触发
    if a.get("core_loop_invoked") is True:
        pass_checks.append("core_loop_invoked_true")
    else:
        fail_checks.append("core_loop_invoked_true")
        errors.append("core_loop_invoked is not True")

    # C5: core_entrypoint == "core.chat"
    # 钉死入口——所有 memory proposal 必须从 core.chat 进入
    if a.get("core_entrypoint") == "core.chat":
        pass_checks.append("core_entrypoint_correct")
    else:
        fail_checks.append("core_entrypoint_correct")
        errors.append(
            f"core_entrypoint={a.get('core_entrypoint')!r} (expected core.chat)"
        )

    # C6: runtime_hook_name == "loop.turn_end"
    # 确认是 turn-end hook 触发，不是其他路径
    if a.get("runtime_hook_name") == "loop.turn_end":
        pass_checks.append("runtime_hook_name_correct")
    else:
        fail_checks.append("runtime_hook_name_correct")
        errors.append(
            f"runtime_hook_name={a.get('runtime_hook_name')!r} "
            f"(expected loop.turn_end)"
        )

    # C7: target_module_proof 非 None
    # observer chain 完整性的核心证据——缺 proof 说明 handler 未通过
    # context.invoke_registered_target 调用 target
    if a.get("target_module_proof_exists"):
        pass_checks.append("target_module_proof_exists")
    else:
        fail_checks.append("target_module_proof_exists")
        errors.append("target_module_proof is None — observer chain broken")

    # C8: target_module == "MemoryPolicy"
    # 验证 handler 调用了正确的注册 target
    if a.get("target_module") == "MemoryPolicy":
        pass_checks.append("target_module_correct")
    else:
        fail_checks.append("target_module_correct")
        errors.append(
            f"target_module={a.get('target_module')!r} (expected MemoryPolicy)"
        )

    # C9: auto_approved == False
    # 硬约束——Phase 1 不实现 auto approve，所有 proposal 必须人工确认
    if a.get("auto_approved") is False:
        pass_checks.append("auto_approved_false")
    else:
        fail_checks.append("auto_approved_false")
        errors.append(
            f"auto_approved={a.get('auto_approved')!r} (expected False)"
        )

    # C10: not_confirmed == True
    # 所有 proposal 初始为未确认状态
    if a.get("not_confirmed") is True:
        pass_checks.append("not_confirmed_true")
    else:
        fail_checks.append("not_confirmed_true")
        errors.append(
            f"not_confirmed={a.get('not_confirmed')!r} (expected True)"
        )

    # C11: provider_kind 匹配 expected（参数化）
    # fake → "fake", real → "real", unknown → fail-closed
    if a.get("provider_kind") == expected_provider_kind:
        pass_checks.append(f"provider_kind_{expected_provider_kind}")
    else:
        fail_checks.append(f"provider_kind_{expected_provider_kind}")
        errors.append(
            f"provider_kind={a.get('provider_kind')!r} "
            f"(expected {expected_provider_kind!r})"
        )

    # C12: external_side_effects 匹配 expected（参数化）
    # fake/real smoke 均为 False——本轮无工具/文件/MCP/memory retain 副作用
    if a.get("external_side_effects") is expected_external_side_effects:
        pass_checks.append(
            f"external_side_effects_{str(expected_external_side_effects).lower()}"
        )
    else:
        fail_checks.append(
            f"external_side_effects_{str(expected_external_side_effects).lower()}"
        )
        errors.append(
            f"external_side_effects={a.get('external_side_effects')!r} "
            f"(expected {expected_external_side_effects})"
        )

    # R1: provider_external_call 匹配 expected（参数化，real smoke 新增）
    # fake → False（无外部 API 调用），real smoke → True（确实调了真实 API）
    if a.get("provider_external_call") is expected_provider_external_call:
        pass_checks.append(
            f"provider_external_call_{str(expected_provider_external_call).lower()}"
        )
    else:
        fail_checks.append(
            f"provider_external_call_{str(expected_provider_external_call).lower()}"
        )
        errors.append(
            f"provider_external_call={a.get('provider_external_call')!r} "
            f"(expected {expected_provider_external_call})"
        )

    # R2: no_silent_retain == True
    # 所有 proposal 必须明确标记 no_silent_retain
    if a.get("no_silent_retain") is True:
        pass_checks.append("no_silent_retain_true")
    else:
        fail_checks.append("no_silent_retain_true")
        errors.append(
            f"no_silent_retain={a.get('no_silent_retain')!r} (expected True)"
        )

    # R3: real_episodes_read == False
    # Phase 1 不读取真实 memory episodes
    if a.get("real_episodes_read") is False:
        pass_checks.append("real_episodes_read_false")
    else:
        fail_checks.append("real_episodes_read_false")
        errors.append(
            f"real_episodes_read={a.get('real_episodes_read')!r} (expected False)"
        )

    # C13: no_errors 由调用方汇总判定

    return {
        "pass_checks": pass_checks,
        "fail_checks": fail_checks,
        "errors": errors,
    }


def build_overclaim_prevention_section() -> str:
    """生成 Memory branch behavior 验证范围声明（overclaim prevention）。

    中文学习边界——为什么需要这个声明：
    - Memory proposal branch behavior 只是 Layer 1（proposal），不是 full Memory E2E
    - 报告必须明确标注已验证和未验证项，避免读者误以为 Memory 系统已可生产使用
    - 后续工作应引用 Unified Runtime Flow Contract，而不是新增 Anchor family

    Returns:
        overclaim prevention 文本块（用于 dogfood 报告末尾）
    """
    lines = [
        "=" * 60,
        "Memory Proposal Branch Behavior 验证范围",
        "=" * 60,
        "",
        "已验证（本 branch behavior 范围内）：",
        "  [x] core.chat 统一入口",
        "  [x] run_main_loop turn-end hook 触发",
        "  [x] RuntimeActionDispatcher.route() 调用",
        "  [x] MemoryTurnEndProposalHandler 处理",
        "  [x] target_module_proof 存在",
        "  [x] evidence_level 正确分类",
        "  [x] pending_review only / no auto approve",
        "  [x] provider_kind 正确标记",
        "",
        "未验证（不在本 branch behavior 范围）：",
        "  [ ] Layer 2: memory approve/confirm/retain 流程",
        "  [ ] Layer 3: memory recall/use",
        "  [ ] ToolRegistry 集成",
        "  [ ] Checkpoint 集成",
        "  [ ] SubAgent 集成",
        "  [ ] 多 turn 对话 memory 累积",
        "  [ ] 跨 session memory 持久化",
        "  [ ] Full real E2E（含工具执行）",
        "",
    ]
    return "\n".join(lines)


def build_action_detail_lines(actions: list[dict[str, Any]]) -> list[str]:
    """生成 action_log 中每个 event 的详细字段展开行。

    用于 dogfood 报告的 Per-event details 段。
    """
    lines: list[str] = []
    for i, action in enumerate(actions, 1):
        lines.append(f"--- Action {i} ---")
        for key in [
            "action_id", "action_type", "source", "status",
            "evidence_level", "dispatcher_origin", "runtime_loop_invoked",
            "core_loop_invoked", "core_entrypoint",
            "runtime_hook_name", "provider_kind", "provider_external_call",
            "external_side_effects", "target_module", "target_module_proof_exists",
            "disposition", "pending_review", "auto_approved", "not_confirmed",
            "real_episodes_read", "secret_like_detected", "no_silent_retain",
        ]:
            lines.append(f"  {key}: {action.get(key)}")
        lines.append("")
    return lines
