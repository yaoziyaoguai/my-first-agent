"""_confirmable_noop: 安全空操作工具——仅用于 ToolRegistry gate confirmation_required branch behavior 验证。

中文学习边界：
_confirmable_noop 与 _safe_noop 同等安全（zero-arg, no shell, no file write,
no external process, no network），唯一区别是 confirmation="always"（区别于
_safe_noop 的 confirmation="never"）。

它用于让 runtime core loop 的 TOOL_GATE action 覆盖 confirmation_required
branch behavior——通过 LoopDependencies.tool_gate_tool_name="_confirmable_noop"
配置，loop 的 TOOL_GATE payload 传递此工具名，gate handler 通过 allowlist 后
走正常 needs_tool_confirmation 检查 → 因 confirmation="always" 返回
gate_disposition="confirmation_required"。

为什么存在：
- _safe_noop 的 confirmation="never" 只能覆盖 allowed branch behavior
- 需要一个零副作用 confirmable tool 覆盖 confirmation_required behavior
- 现有 agent/tools/ 中的所有其他工具都有真实副作用
- 不新增工具则 real_core_loop_runtime_e2e 路径无法覆盖 confirmation_required

不代表什么：
- 不代表放开所有 `_` 前缀工具——allowlist 仍是显式枚举
- 不代表改变 ToolRegistry governance——仍通过 @register_tool 注册
- 不代表新 gate path——allowlist 通过后走同一 needs_tool_confirmation 检查
- 不代表模型可见——`_` 前缀使 get_model_visible_tools() 排除它
"""

from agent.tool_registry import register_tool


@register_tool(
    name="_confirmable_noop",
    description="Internal confirmable no-op tool for ToolRegistry gate verification",
    parameters={},
    confirmation="always",
    capability="local_action",
    risk_level="low",
    output_policy="none",
    meta_tool=False,
)
def _confirmable_noop() -> str:
    """安全空操作——仅用于 ToolRegistry gate 端到端验证（confirmation_required 路径）。"""
    return "confirmable_noop: ok"
