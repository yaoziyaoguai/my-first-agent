"""Tool result feedback branch behavior handler.

中文学习边界：
Tool result feedback 归属 Contract Section 2 "tool execution / confirmation handling" 分支点。
它不是新 Anchor、不是新 capability milestone、不是新 runtime flow。

tool.result 是 tool.gate（pre-execution gating）的互补行为——负责 post-execution
result feedback：接收 tool 执行结果 → 格式化/截断/redact → 生成 prompt section →
注入模型上下文。

这个 handler 注册在 TOOL_RESULT（schema.py 新增），与 TOOL_GATE 并列：
- TOOL_GATE → pre-execution gating (allowed/confirmation_required/blocked)
- TOOL_RESULT → post-execution result feedback (injected/truncated/error/empty)

纯格式化操作，不修改 TOOL_REGISTRY、不调用真实工具、不触发其他 RuntimeAction。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

DEFAULT_CHAR_BUDGET = 500

# 复用 schema.py 的 secret patterns 做基础敏感内容 redact
_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"api[_-]?key\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"token\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"password\s*[:=]\s*(?!\[REDACTED\])[^,\s]+", re.IGNORECASE),
    re.compile(r"Bearer\s+(?!\[REDACTED\])[A-Za-z0-9._-]+", re.IGNORECASE),
)

_REDACTED_PLACEHOLDER = "[已隐藏敏感内容]"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_sensitive_content(text: str) -> str:
    """对疑似包含 API key / token / password 的内容做基础 redact。

    中文学习边界：这不是 LLM-based 敏感内容检测——只做正则匹配。
    真正的敏感内容策略属于 policy 层，不属于 result formatting 层。
    """
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(_REDACTED_PLACEHOLDER, result)
    return result


def format_tool_result(
    tool_name: str,
    tool_output: str | None,
    execution_status: str,
    *,
    rendered_char_budget: int = DEFAULT_CHAR_BUDGET,
) -> dict[str, Any]:
    """格式化 tool result 为 prompt-ready 文本。

    这是 catalog adapter 的 target function——handler 通过
    context.invoke_registered_target() → adapter → 此函数获取 trusted
    target_module_proof。

    Returns:
        dict with keys:
        - formatted_output: str — ready for prompt injection
        - disposition: str — injected/truncated/error/empty
        - original_size: int
        - was_redacted: bool
        - was_truncated: bool
    """
    original = tool_output or ""
    original_size = len(original)
    was_redacted = False
    was_truncated = False
    disposition = "injected"

    # 空结果
    if not original.strip():
        return {
            "formatted_output": "工具执行完成，无输出。",
            "disposition": "empty",
            "original_size": original_size,
            "was_redacted": False,
            "was_truncated": False,
        }

    # 出错
    if execution_status == "error":
        return {
            "formatted_output": f"[工具执行出错] {original[:rendered_char_budget]}",
            "disposition": "error",
            "original_size": original_size,
            "was_redacted": False,
            "was_truncated": len(original) > rendered_char_budget,
        }

    # 正常结果：先 redact，再截断
    redacted = _redact_sensitive_content(original)
    was_redacted = redacted != original

    if len(redacted) > rendered_char_budget:
        redacted = redacted[: rendered_char_budget - 1] + "…"
        was_truncated = True
        disposition = "truncated"

    return {
        "formatted_output": redacted,
        "disposition": disposition,
        "original_size": original_size,
        "was_redacted": was_redacted,
        "was_truncated": was_truncated,
    }


def _build_tool_result_section(
    formatted_output: str,
    tool_name: str,
    disposition: str,
) -> str:
    """组装 tool result prompt section。

    中文学习边界：使用与 memory recall 一致的 --- Section Name --- 标记格式。
    """
    status_note = {
        "injected": "",
        "truncated": "（输出已截断）",
        "error": "（执行出错）",
        "empty": "（无输出）",
    }.get(disposition, "")

    return (
        f"--- Tool Result ---\n"
        f"工具: {tool_name}{status_note}\n"
        f"结果: {formatted_output}"
    )


class ToolResultFeedbackHandler:
    """Tool result feedback handler — post-execution result injection。

    中文学习边界：
    这个 handler 不执行工具、不修改 TOOL_REGISTRY、不触发 TOOL_GATE。
    它只负责：接收已执行的 tool result → 格式化 → 生成 prompt section → 返回 evidence。

    与 MemoryRecallHandler 的对称性：
    - MemoryRecallHandler: store → snapshot → prompt section → system prompt
    - ToolResultFeedbackHandler: tool result → format → prompt section → model context

    构造：
        handler = ToolResultFeedbackHandler(store=InMemoryMemoryStore())

    store 参数为未来 tool result 可能触发 memory proposal 预留——当前不写 store。
    """

    def __init__(self, *, store=None) -> None:
        from agent.memory_store import InMemoryMemoryStore

        self._store = store or InMemoryMemoryStore()

    def handle(self, request, context):
        """处理 TOOL_RESULT action。

        从 payload 提取 tool result → 通过 catalog adapter 格式化 →
        生成 prompt section → 返回 evidence。

        Args:
            request: RuntimeActionRequest with payload keys:
                tool_name (str, required), tool_output (str|None, required),
                execution_status (str, default "success")
            context: RuntimeActionContext
        """
        payload = dict(request.payload)
        tool_name = payload.get("tool_name")
        # tool_output: 区分 "key missing" (None from .get()) vs
        # "value is None" ("tool_output" in payload)
        tool_output_missing = "tool_output" not in payload
        tool_output = payload.get("tool_output")
        execution_status = str(payload.get("execution_status") or "success")
        rendered_char_budget = int(payload.get("rendered_char_budget") or DEFAULT_CHAR_BUDGET)

        # 验证必填字段
        if tool_name is None:
            return context.success(
                handler_name=type(self).__name__,
                target_module="ToolRuntime",
                payload={
                    "disposition": "failed",
                    "error": "missing required field: tool_name",
                    "prompt_section": "",
                },
                observed_call=None,
                evidence_extra={
                    "validation_failed": True,
                    "missing_field": "tool_name",
                    "external_side_effects": False,
                    "read_only_operation": True,
                    "no_tool_registry_modification": True,
                },
            )

        if tool_output_missing:
            return context.success(
                handler_name=type(self).__name__,
                target_module="ToolRuntime",
                payload={
                    "disposition": "failed",
                    "error": "missing required field: tool_output",
                    "tool_name": tool_name,
                    "prompt_section": "",
                },
                observed_call=None,
                evidence_extra={
                    "tool_name": tool_name,
                    "execution_status": execution_status,
                    "validation_failed": True,
                    "missing_field": "tool_output",
                    "external_side_effects": False,
                    "read_only_operation": True,
                    "no_tool_registry_modification": True,
                },
            )

        # ── 通过 catalog adapter 获取 trusted target_module_proof ──────────
        # 中文学习注释：context.invoke_registered_target() 是 trusted target
        # invocation 的唯一入口。handler 不自己构造 proof，也不绕过 catalog。
        observed = context.invoke_registered_target(
            target_module="ToolRuntime",
            operation="format_tool_result",
            payload={
                "tool_name": tool_name,
                "tool_output": tool_output,
                "execution_status": execution_status,
                "rendered_char_budget": rendered_char_budget,
            },
        )

        formatted: dict[str, Any] = observed.value
        formatted_output: str = formatted.get("formatted_output", "")
        disposition: str = formatted.get("disposition", "injected")

        # ── 生成 prompt section ────────────────────────────────────────────
        prompt_section = _build_tool_result_section(
            formatted_output, tool_name, disposition
        )

        return context.success(
            handler_name=type(self).__name__,
            target_module="ToolRuntime",
            payload={
                "disposition": disposition,
                "tool_name": tool_name,
                "execution_status": execution_status,
                "prompt_section": prompt_section,
                "result_original_size": formatted.get("original_size", 0),
                "result_was_redacted": formatted.get("was_redacted", False),
                "result_was_truncated": formatted.get("was_truncated", False),
            },
            observed_call=observed,
            evidence_extra={
                "tool_name": tool_name,
                "execution_status": execution_status,
                "disposition": disposition,
                "result_original_size": formatted.get("original_size", 0),
                "result_was_redacted": formatted.get("was_redacted", False),
                "result_was_truncated": formatted.get("was_truncated", False),
                "external_side_effects": False,
                "read_only_operation": True,
                "no_tool_registry_modification": True,
                "no_tool_invocation": True,
                "no_memory_side_effects": True,
            },
        )
