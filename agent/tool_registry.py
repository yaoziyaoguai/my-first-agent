TOOL_REGISTRY = {}


def register_tool(name, description, parameters, confirmation="always", pre_execute=None, post_execute=None):
    def decorator(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "confirmation": confirmation,
            "func": func,
            "pre_execute": pre_execute,
            "post_execute": post_execute,
        }
        return func
    return decorator


def get_tool_definitions():
    definitions = []
    for name, info in TOOL_REGISTRY.items():
        definitions.append({
            "name": info["name"],
            "description": info["description"],
            "input_schema": {
                "type": "object",
                "properties": info["parameters"],
                "required": list(info["parameters"].keys()),
            },
        })
    return definitions


def get_allowed_tools():
    return set(TOOL_REGISTRY.keys())


def execute_tool(name, tool_input, context=None):
    if name not in TOOL_REGISTRY:
        return f"工具 '{name}' 不在允许列表中"

    info = TOOL_REGISTRY[name]

    # 执行前钩子
    if info.get("pre_execute"):
        try:
            block_reason = info["pre_execute"](name, tool_input, context)
        except Exception as e:
            return f"[工具 {name} 的 pre_execute 钩子异常] {e}"
        if block_reason:
            return block_reason

    # 执行工具函数：任何异常都转换为字符串返回，确保调用方一定能拿到
    # 一个可写入 tool_result 的结果，避免 messages 出现悬空 tool_use。
    try:
        result = info["func"](**tool_input)
    except Exception as e:
        return f"[工具 {name} 执行异常] {type(e).__name__}: {e}"

    # 执行后钩子
    if info.get("post_execute"):
        try:
            result = info["post_execute"](name, tool_input, result)
        except Exception as e:
            return f"[工具 {name} 的 post_execute 钩子异常] {e}"

    return result


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