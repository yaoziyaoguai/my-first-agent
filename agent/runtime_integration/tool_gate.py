"""ToolRegistry RuntimeAction gate handler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest

_FORBIDDEN_TOOL_NAMES = frozenset({"bash", "shell", "run_shell"})


@dataclass(frozen=True, slots=True)
class DogfoodOverlayTool:
    """dogfood-local fake tool 描述。

    它不是 ToolRegistry entry，不持久化，也不执行真实 IO。
    """

    name: str
    requested_capability: str

    def block(self) -> dict[str, Any]:
        return {
            "overlay_tool_name": self.name,
            "resolved_test_tool_name": self.name,
            "dangerous_tool_function_invoked": False,
        }


class ToolGateHandler:
    """通过 RuntimeAction 检查 ToolRegistry gate。

    fake.* overlay 与 production ToolRegistry 是两个命名空间；handler 只持有
    本实例的 overlay dict，不写入 `agent.tool_registry.TOOL_REGISTRY`。
    """

    def __init__(self, *, dogfood_overlay: dict[str, DogfoodOverlayTool] | None = None) -> None:
        self._dogfood_overlay = dict(dogfood_overlay or {})

    def handle(self, request: RuntimeActionRequest, context: RuntimeActionContext):
        import agent.tools  # noqa: F401 - ensure production tools are registered
        from agent.tool_registry import (
            TOOL_REGISTRY,
            _normalize_tool_name,
            get_model_visible_tools,
            needs_tool_confirmation,
        )

        payload = dict(request.payload)
        _raw_tool_name = str(payload.get("tool_name") or "")
        requested_capability = str(payload.get("requested_capability") or "")
        skill_allowed_tools = payload.get("skill_allowed_tools")
        active_skill_id = payload.get("active_skill_id")

        # USER_RECHECK-P1-001: 部分 provider (kimi-k2.5) 剥离 namespace 前缀，
        # 将 demo.echo_task_summary → echo_task_summary。归一化为注册表全名，
        # 使 skill_allowed_tools 检查、TOOL_REGISTRY lookup 等后续逻辑使用一致的全名。
        _normalized = _normalize_tool_name(_raw_tool_name)
        tool_name = _normalized if _normalized is not None else _raw_tool_name

        if not tool_name:
            # 中文学习注释：当 action_type 为 tool.request 且 tool_name 为空时，
            # 这是 turn-end hook 的 L3 evidence dispatch（非模型驱动的 tool request）。
            # handler 通过 invoke_registered_target 获得完整 target_module_proof
            # 证据链，返回 failed disposition 但不影响现有模型输出驱动的 tool gating。
            if str(request.action_type) == "tool.request":
                observed = context.invoke_registered_target(
                    target_module="ToolRegistry",
                    operation="lookup_and_risk_check",
                    payload={"tool_name": ""},
                )
                return context.failed(
                    handler_name=type(self).__name__,
                    target_module="ToolRegistry",
                    payload={
                        "gate_disposition": None,
                        "rejection_reason": "no tool requested at turn-end",
                    },
                    observed_call=observed,
                    evidence_extra={
                        "decision": "failed",
                        "no_tool_requested": True,
                    },
                    error_safe_preview="no tool requested at turn-end",
                )
            return context.failed(
                handler_name=type(self).__name__,
                target_module="ToolRegistry",
                payload={"gate_disposition": None, "rejection_reason": "tool_name is required"},
                observed_call=None,
                evidence_extra={
                    "decision": "failed",
                    "runtime_e2e_disqualified_reason": "tool_name is required",
                },
                error_safe_preview="tool_name is required",
            )

        # Loop 2.2b: active skill allowed_tools enforcement — 在 tool registry
        # lookup 之前检查，非允许工具直接 rejected，不进入 execute_single_tool。
        # 安全策略检查，不走 invoke_registered_target（无对应 catalog entry），
        # evidence 由 TOOL_GATE dispatch 自身提供。
        # Loop 5: evidence_extra 中显式包含 policy_path/rejection_reason，
        # 与 allowed path 的 **result_payload 展开对齐，dogfood 脚本可统一从
        # evidence 读取 gate disposition 字段。
        # v1.1: BASE_TOOLS 不受 skill allowed_tools 约束——
        # read_file / read_file_lines / mark_step_complete / request_user_input
        # 在 Skill 激活后仍可用，不因不在 skill allowed_tools 中被拒绝。
        from agent.tool_scope import is_base_tool

        if (
            skill_allowed_tools
            and tool_name not in skill_allowed_tools
            and not is_base_tool(tool_name)
        ):
            return context.rejected(
                handler_name=type(self).__name__,
                target_module="ToolRegistry",
                payload={
                    "gate_disposition": "rejected",
                    "risk_level": "low",
                    "policy_path": "skill_allowed_tools→rejected",
                    "rejection_reason": "tool not in active skill allowed_tools",
                    "registry_handler_invoked": True,
                    "target_module_invoked": False,
                    "dangerous_tool_function_invoked": False,
                },
                observed_call=None,
                evidence_extra={
                    "requested_tool_name": tool_name,
                    "requested_capability": requested_capability,
                    "capability_type": "skill_tool_constraint",
                    "production_capability": True,
                    "production_registry_found": False,
                    "dogfood_overlay_found": False,
                    "decision": "rejected",
                    "skill_allowed_tools": list(skill_allowed_tools),
                    "active_skill_id": active_skill_id,
                    "policy_path": "skill_allowed_tools→rejected",
                    "rejection_reason": "tool not in active skill allowed_tools",
                    "execution_suppressed": True,
                },
                error_safe_preview="tool not in active skill allowed_tools",
            )

        production_registry_found = tool_name in TOOL_REGISTRY
        if tool_name.startswith("fake."):
            return self._handle_fake_tool(
                context=context,
                tool_name=tool_name,
                requested_capability=requested_capability,
                production_registry_found=production_registry_found,
            )

        observed = context.invoke_registered_target(
            target_module="ToolRegistry",
            operation="lookup_and_risk_check",
            payload={"tool_name": tool_name},
        )
        entry = observed.value
        visible_names = {item.get("name") for item in get_model_visible_tools()}

        if tool_name in _FORBIDDEN_TOOL_NAMES:
            gate_disposition = "rejected"
            decision = "rejected"
            risk_level = "high"
            rejection_reason = "shell-like tool is out of scope"
        elif entry is None:
            gate_disposition = None
            decision = "not_found"
            risk_level = "unknown"
            rejection_reason = "tool not found in production ToolRegistry"
        elif tool_name.startswith("_"):
            # 最小 allowlist：只放行 _safe_noop / _confirmable_noop
            # （内部 branch behavior 验证工具），其他 `_` 前缀工具仍 blocked
            # _safe_noop 通过 allowlist 后走正常 confirmation policy 检查
            # （needs_tool_confirmation 返回 False → gate_disposition="allowed"）。
            # _confirmable_noop 通过 allowlist 后走同一 needs_tool_confirmation 检查
            # （confirmation="always" → gate_disposition="confirmation_required"）。
            if tool_name in ("_safe_noop", "_confirmable_noop"):
                risk_level = str(entry.get("risk_level", "low"))
                tool_args = dict(payload.get("tool_args") or {})
                confirmation = needs_tool_confirmation(tool_name, tool_args)
                if confirmation == "block":
                    gate_disposition = "rejected"
                    decision = "rejected"
                    rejection_reason = "tool policy blocked request"
                elif confirmation is True:
                    gate_disposition = "confirmation_required"
                    decision = "confirmation_required"
                    rejection_reason = None
                else:
                    gate_disposition = "allowed"
                    decision = "allowed"
                    rejection_reason = None
            else:
                gate_disposition = "rejected"
                decision = "rejected"
                risk_level = str(entry.get("risk_level", "medium"))
                rejection_reason = "internal tool is not in tool gate allowlist"
        elif tool_name not in visible_names:
            gate_disposition = "rejected"
            decision = "rejected"
            risk_level = str(entry.get("risk_level", "medium"))
            rejection_reason = "tool is not model-visible"
        else:
            risk_level = str(entry.get("risk_level", "medium"))
            confirmation = needs_tool_confirmation(tool_name, dict(payload.get("tool_args") or {}))
            if confirmation == "block":
                gate_disposition = "rejected"
                decision = "rejected"
                rejection_reason = "tool policy blocked request"
            elif confirmation is True:
                gate_disposition = "confirmation_required"
                decision = "confirmation_required"
                rejection_reason = None
            else:
                gate_disposition = "allowed"
                decision = "allowed"
                rejection_reason = None

        result_payload = {
            "gate_disposition": gate_disposition,
            "risk_level": risk_level,
            "policy_path": "tool_registry→risk_check",
            "rejection_reason": rejection_reason,
            "registry_handler_invoked": True,
            "target_module_invoked": False,
            "dangerous_tool_function_invoked": False,
        }
        # 构建 evidence_extra，包含 skill_allowed_tools（如有）
        # Loop 3: allowed path 也要携带 skill_allowed_tools，确保
        # D05 dogfood 能够通过 evidence 验证 lifecycle→mediator→gate 链路
        evidence_extra: dict[str, Any] = {
            **result_payload,
            "requested_tool_name": tool_name,
            "requested_capability": requested_capability,
            "capability_type": "production_tool_registry",
            "production_capability": True,
            "resolved_tool_name": tool_name if entry is not None else None,
            "production_registry_found": production_registry_found,
            "dogfood_overlay_found": False,
            "decision": decision,
        }
        if skill_allowed_tools:
            evidence_extra["skill_allowed_tools"] = list(skill_allowed_tools)
        if active_skill_id:
            evidence_extra["active_skill_id"] = active_skill_id
        return context.result(
            status="confirmation_required" if gate_disposition == "confirmation_required" else (
                "success" if gate_disposition == "allowed" else "rejected"
            ),
            handler_name=type(self).__name__,
            target_module="ToolRegistry",
            payload=result_payload,
            observed_call=observed,
            evidence_extra=evidence_extra,
        )

    def _handle_fake_tool(
        self,
        *,
        context: RuntimeActionContext,
        tool_name: str,
        requested_capability: str,
        production_registry_found: bool,
    ):
        overlay_tool = self._dogfood_overlay.get(tool_name)
        if production_registry_found:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="DogfoodFakeToolOverlay",
                payload={
                    "gate_disposition": None,
                    "risk_level": "high",
                    "registry_handler_invoked": True,
                    "target_module_invoked": False,
                    "dangerous_tool_function_invoked": False,
                },
                observed_call=None,
                evidence_extra={
                    "requested_tool_name": tool_name,
                    "requested_capability": requested_capability,
                    "capability_type": "dogfood_fake_overlay_blocked_path",
                    "production_capability": False,
                    "production_registry_found": True,
                    "dogfood_overlay_found": overlay_tool is not None,
                    "decision": "failed",
                    "runtime_e2e_disqualified_reason": (
                        "fake tool exists in production ToolRegistry"
                    ),
                },
                error_safe_preview="fake tool exists in production ToolRegistry",
            )
        if overlay_tool is None:
            return context.failed(
                handler_name=type(self).__name__,
                target_module="DogfoodFakeToolOverlay",
                payload={
                    "gate_disposition": None,
                    "risk_level": "high",
                    "registry_handler_invoked": True,
                    "target_module_invoked": False,
                    "dangerous_tool_function_invoked": False,
                },
                observed_call=None,
                evidence_extra={
                    "requested_tool_name": tool_name,
                    "requested_capability": requested_capability,
                    "capability_type": "dogfood_fake_overlay_blocked_path",
                    "production_capability": False,
                    "production_registry_found": False,
                    "dogfood_overlay_found": False,
                    "decision": "failed",
                    "runtime_e2e_disqualified_reason": "fake tool missing from dogfood overlay",
                },
                error_safe_preview="fake tool missing from dogfood overlay",
            )

        observed = context.invoke_registered_target(
            target_module="DogfoodFakeToolOverlay",
            operation="block",
            payload={"overlay_tool": overlay_tool},
        )
        overlay_result = dict(observed.value)
        evidence_extra = {
            "requested_tool_name": tool_name,
            "requested_capability": requested_capability or overlay_tool.requested_capability,
            "capability_type": "dogfood_fake_overlay_blocked_path",
            "production_capability": False,
            "production_registry_found": False,
            "dogfood_overlay_found": True,
            "overlay_tool_name": overlay_result["overlay_tool_name"],
            "resolved_test_tool_name": overlay_result["resolved_test_tool_name"],
            "registry_handler_invoked": True,
            "target_module_invoked": True,
            "dangerous_tool_function_invoked": False,
            "decision": "blocked",
        }
        return context.rejected(
            handler_name=type(self).__name__,
            target_module="DogfoodFakeToolOverlay",
            payload={
                "gate_disposition": None,
                "risk_level": "high",
                "policy_path": "dogfood_overlay→blocked",
                "rejection_reason": "fake high-risk dogfood tool blocked",
                **{key: evidence_extra[key] for key in (
                    "registry_handler_invoked",
                    "target_module_invoked",
                    "dangerous_tool_function_invoked",
                )},
            },
            observed_call=observed,
            evidence_extra=evidence_extra,
            error_safe_preview="fake high-risk dogfood tool blocked",
        )
