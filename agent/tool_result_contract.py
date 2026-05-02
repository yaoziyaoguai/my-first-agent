"""工具结果分类契约。

Tooling Foundation 仍处在 legacy string result 阶段：工具返回字符串，
runtime 通过前缀区分 success / failure / rejected。这个模块把前缀词表和
分类函数集中到一个 seam，避免 tool_executor 继续拥有可迁移的业务分类知识。
未来迁移结构化 ToolResult 时，应优先更新这里。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from agent.display_events import mask_user_visible_secrets

TOOL_FAILURE_PREFIXES = (
    "错误：",
    "读取超时：",
    "HTTP 错误：",
    "读取失败：",
    "执行超时：",
    "[工具 ",
    "[安装失败]",
    "[更新失败]",
    # 未注册工具调用返回「工具 'X' 不在允许列表中」。这必须归入 failed，
    # 否则模型幻觉或调用已下线工具会被误报为执行成功。
    "工具 '",
)

# pre/post-execute 安全检查拒绝使用独立前缀，和普通 failure 区分开。
TOOL_REJECTION_PREFIXES = ("拒绝执行：",)
TOOL_RESULT_PREVIEW_LIMIT = 500

ToolResultStatus = Literal["executed", "failed", "rejected_by_check"]


@dataclass(frozen=True, slots=True)
class ToolResultEnvelope:
    """结构化 ToolResult seam，兼容 legacy string。

    Stage 7 不一次性重写工具执行链路：Anthropic `tool_result.content` 仍可用
    legacy string；本 envelope 先把 status / display event / error taxonomy /
    redacted preview 收口到 result contract 层。executor 继续编排 checkpoint、
    messages 和 UI 投影，不需要拥有前缀业务知识。
    """

    status: ToolResultStatus
    content: str
    display_event_type: str
    status_text: str
    error_type: str | None
    safe_preview: str
    content_length: int
    preview_truncated: bool
    metadata: dict[str, str] = field(default_factory=dict)

    def to_legacy_content(self) -> str:
        """返回当前 Anthropic tool_result 仍在消费的 legacy content。"""

        return self.content


def _error_type_for_result(result: str, status: ToolResultStatus) -> str | None:
    """把 legacy 前缀映射到稳定 error taxonomy。"""

    if status == "executed":
        return None
    if status == "rejected_by_check":
        return "tool_safety_rejected"
    if result.startswith("工具 '"):
        return "unknown_tool"
    if result.startswith("[工具 "):
        return "tool_runtime_error"
    if result.startswith(("读取超时：", "执行超时：")):
        return "timeout"
    if result.startswith("HTTP 错误："):
        return "http_error"
    if result.startswith(("[安装失败]", "[更新失败]")):
        return "skill_lifecycle_error"
    return "tool_failure"


def _safe_preview(result: str, *, limit: int = TOOL_RESULT_PREVIEW_LIMIT) -> tuple[str, bool]:
    """生成脱敏且有边界的预览，供 UI/trace 使用。"""

    redacted = mask_user_visible_secrets(result)
    if len(redacted) <= limit:
        return redacted, False
    return redacted[:limit] + f"...(已截断，原始长度 {len(redacted)} 字符)", True


def classify_tool_result(result: str) -> ToolResultEnvelope:
    """把 legacy string result 投影成结构化 envelope。

    这是迁移 seam，不执行工具、不写 messages、不保存 checkpoint。后续若工具函数
    直接返回 ToolResultEnvelope，也应先在这里统一归一，再由 executor 决定如何
    写 Anthropic `tool_result`。
    """

    status, display_event_type, status_text = classify_tool_outcome(result)
    preview, preview_truncated = _safe_preview(result)
    error_type = _error_type_for_result(result, status)  # type: ignore[arg-type]
    return ToolResultEnvelope(
        status=status,  # type: ignore[arg-type]
        content=result,
        display_event_type=display_event_type,
        status_text=status_text,
        error_type=error_type,
        safe_preview=preview,
        content_length=len(result),
        preview_truncated=preview_truncated,
        metadata={"contract": "legacy_string"},
    )


def classify_tool_outcome(result: str) -> tuple[str, str, str]:
    """把 legacy string result 分类为 runtime/display 可消费的 outcome。

    返回 `(status, display_event_type, status_text)`。这里不写 checkpoint、
    不 append tool_result、不 emit display event；它只负责纯分类，保持 result
    contract 高内聚，也避免 executor 变成工具语义巨石。
    """

    if any(result.startswith(prefix) for prefix in TOOL_REJECTION_PREFIXES):
        return "rejected_by_check", "tool.rejected", "已被工具内部安全检查拒绝。"
    if any(result.startswith(prefix) for prefix in TOOL_FAILURE_PREFIXES):
        return "failed", "tool.failed", "执行失败。"
    return "executed", "tool.completed", "执行完成。"
