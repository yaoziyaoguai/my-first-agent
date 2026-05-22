from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypedDict


ToolResultContent = str | list[Any]
ToolFunction = Callable[..., Any]
PreExecuteHook = Callable[[str, dict[str, Any], Any], ToolResultContent | None]
PostExecuteHook = Callable[[str, dict[str, Any], Any], Any]
ConfirmationPolicy = Literal["always", "never"] | Callable[[dict[str, Any]], bool]


class ToolRegistryEntry(TypedDict):
    """单个工具注册条目的内部契约。

    registry 仍保存普通 dict，避免改变旧测试和 introspection 行为；TypedDict
    只把 public registry/config 边界从匿名 dict 收敛到可审计字段。
    """

    name: str
    description: str
    parameters: dict[str, Any]
    confirmation: ConfirmationPolicy
    func: ToolFunction
    pre_execute: PreExecuteHook | None
    post_execute: PostExecuteHook | None
    meta_tool: bool
    capability: str
    risk_level: str
    output_policy: str


class ToolVisibilityConfig(TypedDict):
    """模型可见工具数量配置的 public API 形状。

    这些值只限制数量预算，不能放宽 capability/risk/hidden-tool 过滤。
    """

    max_total: int
    max_mcp: int


TOOL_REGISTRY: dict[str, ToolRegistryEntry] = {}

# Tooling Foundation 内部治理词表。它们不会暴露给模型，只用于 runtime /
# audit / future MCP adapter 判断工具能力、风险和输出预算。
TOOL_CAPABILITIES = frozenset({
    "local_action",
    "file_read",
    "file_write",
    "command_execution",
    "network_fetch",
    "mcp_tool",
    "skill_lifecycle",
    "runtime_control",
})
TOOL_RISK_LEVELS = frozenset({"low", "medium", "high"})
TOOL_OUTPUT_POLICIES = frozenset({"none", "bounded_text", "artifact_text"})

# ---------------------------------------------------------------------------
# 模型可见工具数量限制（可在测试 / 高级配置中覆盖）
# ---------------------------------------------------------------------------
# 默认值与 get_model_visible_tools() 参数默认值一致。
# 通过 set_model_visible_tool_limits() 覆盖；reset 恢复到内置默认值。
# 安全契约：这些值仅控制数量上限，不能绕过 risk / capability / hidden
# tool 过滤。非法配置（负数等）fail-closed 回退到内置默认值。
_DEFAULT_MAX_TOTAL_TOOLS = 30
_DEFAULT_MAX_MCP_TOOLS = 5

_max_total_tools: int = _DEFAULT_MAX_TOTAL_TOOLS
_max_mcp_tools: int = _DEFAULT_MAX_MCP_TOOLS


def set_model_visible_tool_limits(
    *,
    max_total: int | None = None,
    max_mcp: int | None = None,
) -> None:
    """覆盖模型可见工具数量上限（供测试/高级配置使用）。

    传递 None 的参数保持当前值不变；reset_model_visible_tool_limits()
    恢复到内置默认值。
    """
    global _max_total_tools, _max_mcp_tools
    if max_total is not None:
        if max_total < 1:
            raise ValueError("max_total must be >= 1")
        _max_total_tools = max_total
    if max_mcp is not None:
        if max_mcp < 0:
            raise ValueError("max_mcp must be >= 0")
        _max_mcp_tools = max_mcp


def reset_model_visible_tool_limits() -> None:
    """恢复到内置默认可见工具数量上限。"""
    global _max_total_tools, _max_mcp_tools
    _max_total_tools = _DEFAULT_MAX_TOTAL_TOOLS
    _max_mcp_tools = _DEFAULT_MAX_MCP_TOOLS


def get_model_visible_tool_limits() -> ToolVisibilityConfig:
    """返回当前生效的可见工具数量上限（只读视图）。"""
    return {
        "max_total": _max_total_tools,
        "max_mcp": _max_mcp_tools,
    }


def _validate_metadata(capability, risk_level, output_policy):
    """验证工具治理 metadata，避免每个工具发明自己的 policy 字符串。"""

    if capability not in TOOL_CAPABILITIES:
        raise ValueError(f"未知工具能力类型: {capability}")
    if risk_level not in TOOL_RISK_LEVELS:
        raise ValueError(f"未知工具风险等级: {risk_level}")
    if output_policy not in TOOL_OUTPUT_POLICIES:
        raise ValueError(f"未知工具输出策略: {output_policy}")


def _input_schema(info):
    """生成 Anthropic tool schema；内部 metadata 不应泄漏给模型。"""

    return {
        "type": "object",
        "properties": info["parameters"],
        "required": list(info["parameters"].keys()),
    }


def _confirmation_label(confirmation):
    """把 confirmation 配置投影成可审计字符串，而不是暴露 callable。"""

    if confirmation in ("always", "never"):
        return confirmation
    if callable(confirmation):
        return "dynamic"
    return "unknown"


def register_tool(
    name,
    description,
    parameters,
    confirmation="always",
    pre_execute=None,
    post_execute=None,
    meta_tool=False,
    capability="local_action",
    risk_level="medium",
    output_policy="bounded_text",
):
    """注册一个工具。

    meta_tool=True 表示这是**元工具/控制信号工具**（如 mark_step_complete）——
    它的 tool_use 不会写入 state.conversation.messages，执行也不产生 tool_result。
    元工具的调用只写入 state.task.tool_execution_log 供系统判断使用，
    模型在后续轮次里**看不到**自己之前的元工具调用——避免污染业务对话上下文。
    """
    _validate_metadata(capability, risk_level, output_policy)

    def decorator(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "confirmation": confirmation,
            "func": func,
            "pre_execute": pre_execute,
            "post_execute": post_execute,
            "meta_tool": meta_tool,
            "capability": capability,
            "risk_level": risk_level,
            "output_policy": output_policy,
        }
        return func
    return decorator


def is_meta_tool(name: str) -> bool:
    """查询某工具是否被注册为元工具。"""
    info = TOOL_REGISTRY.get(name)
    if not info:
        return False
    return bool(info.get("meta_tool", False))


def get_tool_definitions():
    """返回完整工具注册表的模型可见 schema（无过滤）。

    这是 registry introspection API，用于审计和测试。
    模型调用应使用 get_model_visible_tools() 以控制上下文预算。
    """
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        definitions.append({
            "name": info["name"],
            "description": info["description"],
            "input_schema": _input_schema(info),
        })
    return definitions


def get_model_visible_tools(
    *,
    max_total: int | None = None,
    max_mcp_tools: int | None = None,
    include_capabilities: frozenset[str] | None = None,
    exclude_capabilities: frozenset[str] | None = None,
    explicit_allowlist: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """返回受控的模型可见工具定义。

    中文学习边界：
    与 get_tool_definitions()（完整 introspection API）不同，本函数专用于
    model call 的 bounded tool list。它通过硬限制防止 MCP tools 无控制地
    侵占模型上下文，同时保证 sanitized description 被使用，raw descriptor
    不会出现在 model-visible tools 中。

    参数：
        max_total: 模型可见工具的最大总数（None = 使用 config 默认值 30）
        max_mcp_tools: MCP tools 最大数量（None = 使用 config 默认值 5）
        include_capabilities: 如果非 None，只包含这些 capability 的工具
        exclude_capabilities: 如果非 None，排除这些 capability 的工具
        explicit_allowlist: 如果非 None，只包含此集合中的工具名

    安全契约：显式传入的值不能绕过 risk / capability / hidden tool 过滤，
    因为这些过滤在 max_total 截断之前独立执行。
    """
    # 使用配置默认值（允许 set_model_visible_tool_limits() 覆盖）
    _limit_total = max_total if max_total is not None else _max_total_tools
    _limit_mcp = max_mcp_tools if max_mcp_tools is not None else _max_mcp_tools

    # 防御：非法值 fail-closed 回退到内置默认值
    if _limit_total < 1:
        _limit_total = _DEFAULT_MAX_TOTAL_TOOLS
    if _limit_mcp < 0:
        _limit_mcp = _DEFAULT_MAX_MCP_TOOLS

    tools: list[dict[str, Any]] = []
    mcp_count = 0

    for name, info in TOOL_REGISTRY.items():
        # 中文学习边界：`_` 前缀工具是 runtime/internal 工具，不能暴露给模型。
        # explicit_allowlist 只能收窄模型可见集合，不能绕过 hidden/internal 过滤。
        if name.startswith("_"):
            continue

        # explicit allowlist 优先
        if explicit_allowlist is not None and name not in explicit_allowlist:
            continue

        cap = info.get("capability", "")
        is_mcp = cap == "mcp_tool"

        # MCP tools 硬限制
        if is_mcp:
            if mcp_count >= _limit_mcp:
                continue
            mcp_count += 1

        # capability filter（不受 max_total 配置影响——安全边界）
        if include_capabilities is not None and cap not in include_capabilities:
            continue
        if exclude_capabilities is not None and cap in exclude_capabilities:
            continue

        tools.append({
            "name": info["name"],
            "description": info["description"],
            "input_schema": _input_schema(info),
        })

        # max_total 硬限制（在所有 filter 之后）
        if len(tools) >= _limit_total:
            break

    return tools


def get_tool_specs():
    """返回 runtime 内部 ToolSpec 投影，不执行工具。

    这是 MCP 前的最小 seam：外部工具未来必须映射到同一组 name/schema/
    capability/risk/output/confirmation 字段，才能复用本地 safety、logging 和
    HITL policy。模型可见 schema 仍由 get_tool_definitions() 单独负责。
    """

    specs = []
    for name, info in TOOL_REGISTRY.items():
        specs.append({
            "name": name,
            "description": info["description"],
            "input_schema": _input_schema(info),
            "confirmation": _confirmation_label(info["confirmation"]),
            "meta_tool": bool(info.get("meta_tool", False)),
            "capability": info["capability"],
            "risk_level": info["risk_level"],
            "output_policy": info["output_policy"],
        })
    return specs


def get_allowed_tools():
    return set(TOOL_REGISTRY.keys())


def _normalize_result(result):
    """把工具返回值规范化为 Anthropic 可接受的 tool_result.content 形态。

    Anthropic 期望 content 是 str 或 list[block]。Python None / 数值 / dict
    都需要转字符串——否则下次 API 调用可能 400。
    """
    if result is None:
        return ""
    if isinstance(result, (str, list)):
        return result
    return str(result)


def _run_pre_execute_hook(name, info, tool_input, context):
    """运行工具 pre-hook，保持 safety guard 在 registry invocation 边界内。

    pre_execute 属于工具调用前的本地 safety seam：它可以拒绝危险输入，但不能
    做 confirmation、checkpoint 或 runtime transition。把这段逻辑留在 registry
    内部 helper，而不是下沉到 core/executor，可避免 runtime 巨石化。
    """

    if info.get("pre_execute"):
        try:
            block_reason = info["pre_execute"](name, tool_input, context)
        except KeyboardInterrupt:
            raise   # Ctrl+C 必须透穿，不能被工具吃掉
        except BaseException as e:
            return f"[工具 {name} 的 pre_execute 钩子异常] {type(e).__name__}: {e}"
        if block_reason:
            return _normalize_result(block_reason)
    return None


def _dispatch_tool_function(name, info, tool_input):
    """执行已注册工具函数，并把普通工具异常转成 legacy 字符串结果。

    这里是 Python callable dispatch 边界，不做 registry lookup，也不写
    tool_result message。返回 `(ok, result)` 是为了保留旧语义：工具函数异常时
    不应继续跑 post_execute hook，但也不能让悬空 tool_use 留给下一轮 API。
    """

    try:
        result = info["func"](**tool_input)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return False, f"[工具 {name} 执行异常] {type(e).__name__}: {e}"
    return True, result


def _run_post_execute_hook(name, info, tool_input, result):
    """运行工具 post-hook，保持结果后处理不进入 runtime/core。

    post_execute 是具体工具的本地收尾 seam，例如 linter 提示或 UX 文案追加。
    它仍属于 registry invocation 的一部分；runtime 只消费最终 result，不应知道
    每个工具的后处理细节。
    """

    if info.get("post_execute"):
        try:
            result = info["post_execute"](name, tool_input, result)
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            return f"[工具 {name} 的 post_execute 钩子异常] {type(e).__name__}: {e}"
    return result


def _invoke_registered_tool(name, info, tool_input, context=None):
    """调用已查到的工具条目，集中处理 hook/dispatch/normalization。

    `execute_tool` 仍负责 registry lookup；本 helper 负责 invocation pipeline。
    这样拆分后边界更清楚，但不引入新类/新模块，也不把 confirmation、
    checkpoint、runtime transition 或 tool_result message 语义放进 registry。
    """

    block_reason = _run_pre_execute_hook(name, info, tool_input, context)
    if block_reason:
        return block_reason

    ok, result = _dispatch_tool_function(name, info, tool_input)
    if not ok:
        return result

    result = _run_post_execute_hook(name, info, tool_input, result)

    # 统一规范化——None/dict/数值都转成字符串，保证 tool_result.content 合法。
    return _normalize_result(result)


def execute_tool(name, tool_input, context=None):
    if name not in TOOL_REGISTRY:
        return f"工具 '{name}' 不在允许列表中"

    info = TOOL_REGISTRY[name]
    return _invoke_registered_tool(name, info, tool_input, context)


def needs_tool_confirmation(name, tool_input):
    if name not in TOOL_REGISTRY:
        return True
    confirmation = TOOL_REGISTRY[name]["confirmation"]
    if confirmation == "always":
        return True
    elif confirmation == "never":
        return False
    elif callable(confirmation):
        return confirmation(tool_input)
    return True
