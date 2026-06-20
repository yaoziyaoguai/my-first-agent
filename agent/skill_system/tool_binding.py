"""Skill Tool Binding —— 连接 Skill allowed_tools 与 ToolRegistry 的安全边界。

设计原则（来自 RFC Sec 3 / SDD Sec 6）：
- allowed_tools 是上限，不是授权绕过
- ToolRegistry 仍是一切的 authority（risk / confirmation / execution）
- Skill 只能请求工具，不能直接执行
- hidden / internal 工具不可暴露
- high-risk 工具 confirmation 保留
- 无效 allowed_tools fail closed 或 warn
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agent.skill_system.descriptor import SkillDescriptor

# ---- ToolRegistry 接口（Protocol，不依赖具体实现） ----


class ToolRegistryView(Protocol):
    """ToolRegistry 的最小只读接口——Skill binding 只需要查询能力。

    真实实现是 agent.tool_registry.TOOL_REGISTRY dict，但 binding 通过
    Protocol 解耦，测试可用 mock。
    """

    def is_registered(self, name: str) -> bool: ...

    def get_risk(self, name: str) -> str: ...

    def get_confirmation(self, name: str) -> str: ...

    def is_hidden(self, name: str) -> bool: ...


# ---- 结果类型 ----


@dataclass(frozen=True)
class ToolBindingResult:
    """单个工具请求的绑定检查结果。"""

    tool_name: str
    allowed: bool
    risk_level: str
    requires_confirmation: bool
    reason: str


# ---- Binding ----


class SkillToolBinding:
    """将 SkillDescriptor 的 allowed_tools 与 ToolRegistry 进行安全绑定。

    检查顺序：
    1. 工具是否在 Skill 的 allowed_tools 中？（上限检查）
    2. 工具是否在 ToolRegistry 中注册？
    3. 工具是否 hidden？（hidden 不可暴露）
    4. 工具 risk level 是什么？
    5. 是否需要 confirmation？

    Usage::

        desc = registry.get_descriptor("my-skill")
        binding = SkillToolBinding(desc, tool_registry_view)
        result = binding.check("read_file")
        if result.allowed:
            ...
    """

    def __init__(self, descriptor: SkillDescriptor, registry: ToolRegistryView):
        self._descriptor = descriptor
        self._registry = registry
        self._allowed_set = set(descriptor.allowed_tools)

    def check(self, tool_name: str) -> ToolBindingResult:
        """检查单个工具是否可在当前 Skill 上下文中使用。"""
        # Step 1: allowed_tools 上限检查
        if tool_name not in self._allowed_set:
            return ToolBindingResult(
                tool_name=tool_name,
                allowed=False,
                risk_level="unknown",
                requires_confirmation=False,
                reason=(
                    f"工具 '{tool_name}' 不在 Skill "
                    f"'{self._descriptor.name}' 的 allowed_tools 中"
                ),
            )

        # Step 2: ToolRegistry 注册检查
        if not self._registry.is_registered(tool_name):
            return ToolBindingResult(
                tool_name=tool_name,
                allowed=False,
                risk_level="unknown",
                requires_confirmation=False,
                reason=f"工具 '{tool_name}' 未在 ToolRegistry 中注册",
            )

        # Step 3: hidden tool 检查
        if self._registry.is_hidden(tool_name):
            return ToolBindingResult(
                tool_name=tool_name,
                allowed=False,
                risk_level="hidden",
                requires_confirmation=False,
                reason=f"工具 '{tool_name}' 是 hidden/internal 工具，不可暴露给 Skill",
            )

        # Step 4: risk level
        risk = self._registry.get_risk(tool_name)
        if risk not in ("low", "medium", "high"):
            risk = "medium"  # 未知风险保守处理

        # Step 5: confirmation
        confirmation = self._registry.get_confirmation(tool_name)
        requires_conf = confirmation in ("always",) or risk == "high"

        return ToolBindingResult(
            tool_name=tool_name,
            allowed=True,
            risk_level=risk,
            requires_confirmation=requires_conf,
            reason="ok",
        )

    def check_all(self) -> dict[str, ToolBindingResult]:
        """对 allowed_tools 中所有工具进行批量检查。"""
        return {name: self.check(name) for name in self._allowed_set}


def validate_tool_request(
    descriptor: SkillDescriptor,
    tool_name: str,
    registry: ToolRegistryView,
) -> ToolBindingResult:
    """便捷函数：快速验证单个工具请求。

    这是 SkillToolBinding.check() 的简写入口。
    """
    binding = SkillToolBinding(descriptor, registry)
    return binding.check(tool_name)
