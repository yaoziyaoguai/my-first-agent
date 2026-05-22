"""_safe_noop: 安全空操作工具——仅用于 ToolRegistry gate branch behavior 验证。

中文学习边界：
_safe_noop 是唯一允许通过 `_` 前缀 gate 限制的内部 safe no-op 工具。
它以 `_` 下划线开头，因此 get_model_visible_tools() 会将其排除（模型不可见），
但 ToolGateHandler 通过最小 allowlist 仍可在 TOOL_REGISTRY 中查到它。

为什么存在：
- ToolRegistry gate allowed branch behavior 需要一个零副作用的生产工具来验证 gate 路径
- 现有 agent/tools/ 中的所有工具都有真实副作用（shell、file_write、network_fetch）
- _safe_noop 是唯一零副作用的 production 工具：不执行 shell、不写文件、不调外部进程、不访问网络

不代表什么：
- 不代表放开所有 `_` 前缀工具——其他 `_` 前缀工具仍被 gate blocked
- 不代表 fake ToolRegistry——它注册在 production TOOL_REGISTRY 中
- 不代表可被模型调用——get_model_visible_tools() 的 `_` prefix filter 会排除它
"""

from agent.tool_registry import register_tool


@register_tool(
    name="_safe_noop",
    description="Internal safe no-op tool for ToolRegistry gate verification",
    parameters={},
    confirmation="never",
    capability="local_action",
    risk_level="low",
    output_policy="none",
    meta_tool=False,
)
def _safe_noop() -> str:
    """安全空操作——仅用于 ToolRegistry gate 端到端验证。"""
    return "noop: ok"
