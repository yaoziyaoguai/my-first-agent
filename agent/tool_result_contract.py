"""工具结果分类契约。

Tooling Foundation 仍处在 legacy string result 阶段：工具返回字符串，
runtime 通过前缀区分 success / failure / rejected。这个模块把前缀词表和
分类函数集中到一个 seam，避免 tool_executor 继续拥有可迁移的业务分类知识。
未来迁移结构化 ToolResult 时，应优先更新这里。
"""

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
