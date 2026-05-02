TOOL_REGISTRY = {}

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
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        definitions.append({
            "name": info["name"],
            "description": info["description"],
            "input_schema": _input_schema(info),
        })
    return definitions


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
