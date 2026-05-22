"""Tool Anchor dogfood 共享检查模块。

中文学习边界：
Tool Anchor fake/real dogfood 共享同一套核心 PASS 标准检查逻辑。
与 memory anchor 对称但独立——Tool Anchor 检查 tool.gate 特有字段
（gate_disposition, decision, production_registry_found 等），不读
memory-specific 字段。

约束：
- 不接触 provider 对象
- 不读 .env
- 不打印 secret
- 只做 evidence 字段的结构化验证

架构依据：docs/plans/velvety-brewing-boole.md §G
"""

from __future__ import annotations

from typing import Any


def find_tool_gate_action(actions: list[dict[str, Any]]) -> dict[str, Any] | None:
    """按 action_type 查找 tool.gate event——不使用 actions[0]/[1]。

    中文学习边界——为什么必须按 action_type 查找：
    - action_log 同时包含 memory.turn_end_proposal 和 tool.gate 两个 event
    - 两个 event 的顺序由 turn-end hook 决定（MEMORY 先，TOOL_GATE 后）
    - 硬编码索引 actions[1] 会因 turn-end hook 改动而静默失效
    - 按 action_type 查找是唯一正确的定位方式
    """
    for action in actions:
        if action.get("action_type") == "tool.gate":
            return action
    return None


def check_tool_anchor_evidence(
    actions: list[dict[str, Any]],
    *,
    expected_tool_name: str = "_safe_noop",
    expected_provider_kind: str = "fake",
    expected_provider_external_call: bool = False,
    expected_external_side_effects: bool = False,
    pre_existing_errors: list[str] | None = None,
) -> dict[str, Any]:
    """对 action_log 执行 Tool Anchor PASS 标准检查。

    参数化 expected 值使得同一套检查逻辑可用于 fake/real 两种模式：
    - fake: provider_kind="fake", provider_external_call=False, external_side_effects=False
    - real smoke: provider_kind="real", provider_external_call=True, external_side_effects=False

    中文学习边界——为什么参数化而非两套函数：
    - fake/real 共享同一条 core.chat → run_main_loop → turn-end hook 路径
    - 唯一的差异是 provider metadata 的 expected 值
    - 参数化避免两套独立 PASS 标准漂移

    Returns:
        dict with keys: pass_checks (list[str]), fail_checks (list[str]), errors (list[str])
    """
    errors: list[str] = list(pre_existing_errors or [])
    pass_checks: list[str] = []
    fail_checks: list[str] = []

    # 按 action_type 查找 tool.gate event
    ta = find_tool_gate_action(actions)

    # T1: action_log 中必须存在 tool.gate event
    if ta is not None:
        pass_checks.append("tool_gate_event_found")
    else:
        fail_checks.append("tool_gate_event_found")
        errors.append(
            "tool.gate event not found in action_log — "
            "TOOL_GATE action 可能未被 turn-end hook 发送或被 handler 拒绝"
        )
        return {
            "pass_checks": pass_checks,
            "fail_checks": fail_checks,
            "errors": errors,
        }

    # ── 共享 core loop evidence 字段（与 Memory Anchor 同源验证） ──

    # T2: evidence_level == real_core_loop_runtime_e2e
    if ta.get("evidence_level") == "real_core_loop_runtime_e2e":
        pass_checks.append("evidence_level_correct")
    else:
        fail_checks.append("evidence_level_correct")
        errors.append(
            f"evidence_level={ta.get('evidence_level')!r} "
            f"(expected real_core_loop_runtime_e2e)"
        )

    # T3: core_loop_invoked == True
    if ta.get("core_loop_invoked") is True:
        pass_checks.append("core_loop_invoked_true")
    else:
        fail_checks.append("core_loop_invoked_true")
        errors.append("core_loop_invoked is not True")

    # T4: core_entrypoint == "core.chat"
    if ta.get("core_entrypoint") == "core.chat":
        pass_checks.append("core_entrypoint_correct")
    else:
        fail_checks.append("core_entrypoint_correct")
        errors.append(
            f"core_entrypoint={ta.get('core_entrypoint')!r} (expected core.chat)"
        )

    # T5: runtime_hook_name == "loop.turn_end"
    if ta.get("runtime_hook_name") == "loop.turn_end":
        pass_checks.append("runtime_hook_name_correct")
    else:
        fail_checks.append("runtime_hook_name_correct")
        errors.append(
            f"runtime_hook_name={ta.get('runtime_hook_name')!r} (expected loop.turn_end)"
        )

    # T6: target_module_proof 非 None
    if ta.get("target_module_proof_exists"):
        pass_checks.append("target_module_proof_exists")
    else:
        fail_checks.append("target_module_proof_exists")
        errors.append("target_module_proof is None — observer chain broken")

    # T7: target_module == "ToolRegistry"
    if ta.get("target_module") == "ToolRegistry":
        pass_checks.append("target_module_correct")
    else:
        fail_checks.append("target_module_correct")
        errors.append(
            f"target_module={ta.get('target_module')!r} (expected ToolRegistry)"
        )

    # T8: provider_kind 匹配 expected
    if ta.get("provider_kind") == expected_provider_kind:
        pass_checks.append(f"provider_kind_{expected_provider_kind}")
    else:
        fail_checks.append(f"provider_kind_{expected_provider_kind}")
        errors.append(
            f"provider_kind={ta.get('provider_kind')!r} "
            f"(expected {expected_provider_kind!r})"
        )

    # T9: external_side_effects 匹配 expected
    if ta.get("external_side_effects") is expected_external_side_effects:
        pass_checks.append(
            f"external_side_effects_{str(expected_external_side_effects).lower()}"
        )
    else:
        fail_checks.append(
            f"external_side_effects_{str(expected_external_side_effects).lower()}"
        )
        errors.append(
            f"external_side_effects={ta.get('external_side_effects')!r} "
            f"(expected {expected_external_side_effects})"
        )

    # T10: provider_external_call 匹配 expected
    if ta.get("provider_external_call") is expected_provider_external_call:
        pass_checks.append(
            f"provider_external_call_{str(expected_provider_external_call).lower()}"
        )
    else:
        fail_checks.append(
            f"provider_external_call_{str(expected_provider_external_call).lower()}"
        )
        errors.append(
            f"provider_external_call={ta.get('provider_external_call')!r} "
            f"(expected {expected_provider_external_call})"
        )

    # ── Tool Gate 特有字段 ──

    # T11: requested_tool_name 匹配 expected
    if ta.get("requested_tool_name") == expected_tool_name:
        pass_checks.append("requested_tool_name_correct")
    else:
        fail_checks.append("requested_tool_name_correct")
        errors.append(
            f"requested_tool_name={ta.get('requested_tool_name')!r} "
            f"(expected {expected_tool_name!r})"
        )

    # T12: production_registry_found == True（_safe_noop 应存在）
    if ta.get("production_registry_found") is True:
        pass_checks.append("production_registry_found_true")
    else:
        fail_checks.append("production_registry_found_true")
        errors.append(
            f"production_registry_found={ta.get('production_registry_found')!r} "
            f"(expected True)"
        )

    # T13: gate_disposition == "allowed"（confirmation="never" → 自动通过）
    if ta.get("gate_disposition") == "allowed":
        pass_checks.append("gate_disposition_allowed")
    else:
        fail_checks.append("gate_disposition_allowed")
        errors.append(
            f"gate_disposition={ta.get('gate_disposition')!r} (expected allowed)"
        )

    # T14: dogfood_overlay_found == False（production 路径，不是 fake overlay）
    if ta.get("dogfood_overlay_found") is False:
        pass_checks.append("dogfood_overlay_found_false")
    else:
        fail_checks.append("dogfood_overlay_found_false")
        errors.append(
            f"dogfood_overlay_found={ta.get('dogfood_overlay_found')!r} "
            f"(expected False — must be production path, not fake overlay)"
        )

    # T15: capability_type == "production_tool_registry"
    if ta.get("capability_type") == "production_tool_registry":
        pass_checks.append("capability_type_correct")
    else:
        fail_checks.append("capability_type_correct")
        errors.append(
            f"capability_type={ta.get('capability_type')!r} "
            f"(expected production_tool_registry)"
        )

    # T16: resolved_tool_name 匹配 expected
    if ta.get("resolved_tool_name") == expected_tool_name:
        pass_checks.append("resolved_tool_name_correct")
    else:
        fail_checks.append("resolved_tool_name_correct")
        errors.append(
            f"resolved_tool_name={ta.get('resolved_tool_name')!r} "
            f"(expected {expected_tool_name!r})"
        )

    # T17: decision == "allowed"
    if ta.get("decision") == "allowed":
        pass_checks.append("decision_allowed")
    else:
        fail_checks.append("decision_allowed")
        errors.append(
            f"decision={ta.get('decision')!r} (expected allowed)"
        )

    return {
        "pass_checks": pass_checks,
        "fail_checks": fail_checks,
        "errors": errors,
    }


def build_tool_anchor_overclaim_prevention_section() -> str:
    """生成 Tool Anchor 验证范围声明（overclaim prevention）。

    中文学习边界——为什么需要这个声明：
    - Tool Anchor 只验证 ToolRegistry gate 路径
    - 不覆盖真实工具执行、MCP、Skill、Checkpoint 等
    - 报告必须明确标注已验证和未验证项
    """
    lines = [
        "=" * 60,
        "Tool Anchor 验证范围",
        "=" * 60,
        "",
        "已验证（本锚点范围内）：",
        "  [x] core.chat 统一入口",
        "  [x] run_main_loop turn-end hook 触发 TOOL_GATE",
        "  [x] RuntimeActionDispatcher.route() 调用",
        "  [x] ToolGateHandler 处理",
        "  [x] TOOL_REGISTRY 查找 _safe_noop",
        "  [x] _safe_noop allowlist gate check",
        "  [x] target_module_proof (ToolRegistry) 存在",
        "  [x] evidence_level 正确分类",
        "  [x] gate_disposition=allowed",
        "  [x] provider_kind 正确标记",
        "",
        "未验证（不在本锚点范围）：",
        "  [ ] 真实工具执行（只做了 gate check）",
        "  [ ] file_write / shell / external process 工具",
        "  [ ] MCP 工具 gate check",
        "  [ ] Skill 集成",
        "  [ ] Checkpoint 集成",
        "  [ ] Streaming 集成",
        "  [ ] SubAgent 集成",
        "  [ ] 工具确认交互（confirmation_required）",
        "  [ ] 工具执行结果路由",
        "",
    ]
    return "\n".join(lines)


def build_tool_action_detail_lines(actions: list[dict[str, Any]]) -> list[str]:
    """生成 action_log 中 tool.gate event 的详细字段展开行。"""
    lines: list[str] = []
    ta = find_tool_gate_action(actions)
    if ta is None:
        lines.append("(no tool.gate event found)")
        return lines

    lines.append("--- tool.gate Action ---")
    for key in [
        "action_id", "action_type", "source", "status",
        "evidence_level", "core_loop_invoked", "core_entrypoint",
        "runtime_hook_name", "provider_kind", "provider_external_call",
        "external_side_effects", "target_module", "target_module_proof_exists",
        # tool.gate 特有字段
        "requested_tool_name", "resolved_tool_name",
        "production_registry_found", "dogfood_overlay_found",
        "gate_disposition", "decision", "risk_level",
        "capability_type", "production_capability",
        "rejection_reason",
    ]:
        lines.append(f"  {key}: {ta.get(key)}")
    lines.append("")
    return lines
