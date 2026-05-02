TOOL_REGISTRY = {}

# Tooling Foundation 内部治理词表。它们不会暴露给模型，只用于 runtime /
# audit / future MCP adapter 判断工具能力、风险和输出预算。
TOOL_CAPABILITIES = frozenset({
    "local_action",
    "file_read",
    "file_write",
    "command_execution",
    "network_fetch",
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


def execute_tool(name, tool_input, context=None):
    if name not in TOOL_REGISTRY:
        return f"工具 '{name}' 不在允许列表中"

    info = TOOL_REGISTRY[name]

    # 执行前钩子
    if info.get("pre_execute"):
        try:
            block_reason = info["pre_execute"](name, tool_input, context)
        except KeyboardInterrupt:
            raise   # Ctrl+C 必须透穿，不能被工具吃掉
        except BaseException as e:
            return f"[工具 {name} 的 pre_execute 钩子异常] {type(e).__name__}: {e}"
        if block_reason:
            return _normalize_result(block_reason)

    # 执行工具函数：**任何**异常都转字符串返回（包括 SystemExit——工具误调 exit()
    # 不应当挂掉整个 agent）。KeyboardInterrupt 例外——它必须透穿让用户能中断。
    try:
        result = info["func"](**tool_input)
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        return f"[工具 {name} 执行异常] {type(e).__name__}: {e}"

    # 执行后钩子
    if info.get("post_execute"):
        try:
            result = info["post_execute"](name, tool_input, result)
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            return f"[工具 {name} 的 post_execute 钩子异常] {type(e).__name__}: {e}"

    # 统一规范化——None/dict/数值都转成字符串，保证 tool_result.content 合法
    return _normalize_result(result)


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
