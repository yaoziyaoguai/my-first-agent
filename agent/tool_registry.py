TOOL_REGISTRY = {}


def register_tool(name, description, parameters, confirmation="always"):
    """
    工具注册装饰器
    
    name: 工具名
    description: 工具描述（给模型看）
    parameters: 参数定义（给模型看）
    confirmation: 
        "always" → 全部确认
        "never" → 从不确认
        callable → 调用这个函数来判断，返回 True/False/"block"
    """
    def decorator(func):
        TOOL_REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "confirmation": confirmation,
            "func": func,
        }
        return func
    return decorator


def get_tool_definitions():
    """自动生成 TOOL_DEFINITIONS 列表"""
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
    """自动生成白名单"""
    return set(TOOL_REGISTRY.keys())


def execute_tool(name, tool_input):
    """统一的工具分发"""
    if name not in TOOL_REGISTRY:
        return f"工具 '{name}' 不在允许列表中"
    return TOOL_REGISTRY[name]["func"](**tool_input)


def needs_tool_confirmation(name, tool_input):
    """
    根据注册信息判断是否需要确认
    返回值：
        False → 静默执行
        True → 弹确认
        "block" → 直接拒绝
    """
    if name not in TOOL_REGISTRY:
        return True
    
    confirmation = TOOL_REGISTRY[name]["confirmation"]
    
    if confirmation == "always":
        return True
    elif confirmation == "never":
        return False
    elif callable(confirmation):
        return confirmation(tool_input)
    else:
        return True
