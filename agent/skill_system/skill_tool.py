"""SKILL_SELECT model-owned tool — 模型自主选择 Skill 的工具入口。

将 SKILL_SELECT 注册为 TOOL_REGISTRY 标准工具，出现在 get_model_visible_tools()
中，让模型在对话中自主决定是否调用、何时调用。调用后走标准 ToolRuntimeMediator
pipeline：tool_use → TOOL_GATE → TOOL_INVOKE → TOOL_RESULT → conversation context。

与 keyword fallback 的区别：
- model-owned: 模型主动 tool_use("SKILL_SELECT", {skill_id: "..."}) → _active_skill
  直接设置 + _skill_selected_by_model flag
- keyword fallback: turn-end hook post-hoc keyword matching → SKILL_SELECT dispatch
  via dispatcher → handler 校验加载
"""

from __future__ import annotations

from agent.tool_registry import TOOL_REGISTRY


def _ensure_skill_select_registered():
    """确保 SKILL_SELECT 已在 TOOL_REGISTRY 中注册（幂等）。

    工具 schema 不含动态 enum——模型在 description 中被告知从 [Active Skills]
    列表中选择。运行时由 tool func 校验 skill_id 是否有效。
    """
    if "SKILL_SELECT" in TOOL_REGISTRY:
        return

    # 直接写入 TOOL_REGISTRY（不用 @register_tool 装饰器——工具 func 需要
    # 访问 SkillRegistry，该依赖在 import 时不可用，运行时 lazy import）。
    TOOL_REGISTRY["SKILL_SELECT"] = {
        "name": "SKILL_SELECT",
        "description": (
            "选择一个可用的 Skill 来激活。激活后，Skill 的指令将注入系统提示，"
            "Skill 声明的工具列表将约束后续可用的工具。"
            "如果你不需要使用特定 Skill，不要调用此工具。"
        ),
        "parameters": {
            "skill_id": {
                "type": "string",
                "description": (
                    "要激活的 Skill 名称（从 [Active Skills] 列表中选择）。"
                ),
            },
            "reason": {
                "type": "string",
                "description": "选择此 Skill 的原因（可选）。",
            },
        },
        "required": ["skill_id"],
        "confirmation": "never",
        "func": _skill_select_tool_func,
        "pre_execute": None,
        "post_execute": None,
        "meta_tool": False,
        "capability": "skill_lifecycle",
        "risk_level": "low",
        "output_policy": "bounded_text",
    }


def _skill_select_tool_func(skill_id: str = "", reason: str = ""):
    """SKILL_SELECT 工具执行体——模型自主选择 Skill。

    由 ToolRuntimeMediator → execute_single_tool 调用。
    校验 skill_id、加载 body、更新 _active_skill、返回激活确认。
    unknown/malformed skill_id 返回描述性错误，不 crash。
    """
    if not skill_id or not isinstance(skill_id, str):
        return (
            "SKILL_SELECT 调用缺少有效的 skill_id 参数。"
            "请从 [Active Skills] 列表中选择一个 skill_id 传入。"
        )

    from pathlib import Path

    from agent.skill_system.loader import SkillLoader
    from agent.skill_system.registry import SkillRegistry

    registry = SkillRegistry(roots=[Path("skills")])
    descriptor = registry.get_descriptor(skill_id)

    if descriptor is None or not descriptor.is_visible():
        visible = registry.list_visible()
        visible_names = [s.name for s in visible]
        return (
            f"Skill '{skill_id}' 不可用。"
            f"可用的 Skills: {visible_names if visible_names else '无'}"
        )

    loader = SkillLoader(registry)
    body = loader.load_body(skill_id)
    body_str = str(body)[:2000] if body else ""

    if not body_str:
        return f"Skill '{skill_id}' 无法加载内容（body 为空或加载失败）。"

    allowed_tools = frozenset(descriptor.allowed_tools)

    # Phase 4 (Plan 3): 通过 lifecycle 更新跨 turn active skill 状态
    import agent.core as _core

    _core._active_skill = {
        "skill_id": skill_id,
        "body": body_str,
        "allowed_tools": allowed_tools,
    }
    from agent.skill_system.lifecycle import get_default_lifecycle
    _lc = get_default_lifecycle()
    _lc.activate(
        skill_id=skill_id,
        body=body_str,
        allowed_tools=tuple(allowed_tools),
        activated_by="model_selection",
    )
    # model-owned selection flag — turn-end hook 检查此 flag 跳过 keyword fallback
    _core._skill_selected_by_model = True

    return (
        f"Skill '{skill_id}' 已激活。\n\n"
        f"[Active Skill Instructions]\n{body_str}\n[/Active Skill Instructions]"
    )
