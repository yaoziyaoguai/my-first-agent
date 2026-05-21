"""ToolRegistry RuntimeAction gate handler."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from typing import Any

from agent.runtime_integration.dispatcher import RuntimeActionContext
from agent.runtime_integration.schema import RuntimeActionRequest


_FORBIDDEN_TOOL_NAMES = frozenset({"bash", "shell", "run_shell"})


def _lookup_tool_registry_entry(tool_name: str) -> dict[str, Any] | None:
    """catalog descriptor 绑定的 ToolRegistry lookup adapter。

    中文学习边界：RuntimeAction proof 需要证明实际 callable provenance，不能让
    handler 用 lambda 把任意逻辑贴上 `ToolRegistry` 标签。这个小 adapter 是
    catalog-owned implementation identity，不执行目标工具函数。
    """

    from agent.tool_registry import TOOL_REGISTRY

    return TOOL_REGISTRY.get(tool_name)


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
        from agent.tool_registry import TOOL_REGISTRY, get_model_visible_tools, needs_tool_confirmation

        payload = dict(request.payload)
        tool_name = str(payload.get("tool_name") or "")
        requested_capability = str(payload.get("requested_capability") or "")

        if not tool_name:
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

        production_registry_found = tool_name in TOOL_REGISTRY
        if tool_name.startswith("fake."):
            return self._handle_fake_tool(
                context=context,
                tool_name=tool_name,
                requested_capability=requested_capability,
                production_registry_found=production_registry_found,
            )

        observed = context.observe_module_call(
            target_module="ToolRegistry",
            function_called="ToolRegistry.lookup_and_risk_check",
            call_signature="lookup_and_risk_check(tool_name: str)",
            call=partial(_lookup_tool_registry_entry, tool_name),
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
        elif tool_name not in visible_names or tool_name.startswith("_"):
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
        return context.result(
            status="confirmation_required" if gate_disposition == "confirmation_required" else (
                "success" if gate_disposition == "allowed" else "rejected"
            ),
            handler_name=type(self).__name__,
            target_module="ToolRegistry",
            payload=result_payload,
            observed_call=observed,
            evidence_extra={
                **result_payload,
                "requested_tool_name": tool_name,
                "requested_capability": requested_capability,
                "capability_type": "production_tool_registry",
                "production_capability": True,
                "resolved_tool_name": tool_name if entry is not None else None,
                "production_registry_found": production_registry_found,
                "dogfood_overlay_found": False,
                "decision": decision,
            },
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
                    "runtime_e2e_disqualified_reason": "fake tool exists in production ToolRegistry",
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

        observed = context.observe_module_call(
            target_module="DogfoodFakeToolOverlay",
            function_called="DogfoodOverlayTool.block",
            call_signature="block()",
            call=overlay_tool.block,
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
