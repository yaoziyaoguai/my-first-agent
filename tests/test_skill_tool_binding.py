"""Phase 5: Skill Tool Binding 测试。

测试范围（Skill Tool Binding）：
- allowed_tools 是上限，不是授权绕过
- ToolRegistry risk/capability filtering 仍生效
- high-risk tool confirmation 仍保留
- unknown tool 被阻止
- Skill 可以请求工具但不能直接执行

禁止行为：
- Skill bypass ToolRegistry
- Skill downgrade risk
- Skill execute tools directly
- import legacy
"""
from __future__ import annotations

from agent.skill_system.descriptor import SkillDescriptor
from agent.skill_system.tool_binding import (
    SkillToolBinding,
    ToolBindingResult,
    validate_tool_request,
)

# ---- helpers ----

def _make_descriptor(
    name: str = "test-skill",
    allowed_tools: tuple[str, ...] = ("read_file", "write_file"),
    risk_level: str = "low",
) -> SkillDescriptor:
    return SkillDescriptor(
        name=name,
        description="A test skill",
        version="0.1.0",
        status="active",
        risk_level=risk_level,  # type: ignore[arg-type]
        allowed_tools=allowed_tools,
    )


# ---- Mock ToolRegistry entry ----

class _MockToolRegistry:
    """模拟 ToolRegistry，不依赖真实注册。"""

    def __init__(self, tools: dict | None = None):
        self._tools = tools or {}
        self._capabilities: dict[str, str] = {}
        self._risks: dict[str, str] = {}
        self._confirmations: dict[str, str] = {}
        self._hidden: set[str] = set()

    def add_tool(self, name: str, capability: str = "local_action",
                 risk: str = "low", confirmation: str = "never",
                 hidden: bool = False):
        self._tools[name] = True
        self._capabilities[name] = capability
        self._risks[name] = risk
        self._confirmations[name] = confirmation
        if hidden:
            self._hidden.add(name)
        return self

    def is_registered(self, name: str) -> bool:
        return name in self._tools

    def get_risk(self, name: str) -> str:
        return self._risks.get(name, "low")

    def get_confirmation(self, name: str) -> str:
        return self._confirmations.get(name, "never")

    def is_hidden(self, name: str) -> bool:
        return name in self._hidden


# ==================================================================
# allowed_tools 上限检查
# ==================================================================

def test_tool_in_allowed_list_passes():
    """在 allowed_tools 中的工具请求通过。"""
    desc = _make_descriptor(allowed_tools=("read_file",))
    registry = _MockToolRegistry().add_tool("read_file")
    binding = SkillToolBinding(desc, registry)
    result = binding.check("read_file")
    assert result.allowed is True


def test_tool_not_in_allowed_list_blocked():
    """不在 allowed_tools 中的工具请求被阻止。"""
    desc = _make_descriptor(allowed_tools=("read_file",))
    registry = _MockToolRegistry().add_tool("write_file")
    binding = SkillToolBinding(desc, registry)
    result = binding.check("write_file")
    assert result.allowed is False
    assert (
        "allowed_tools" in result.reason.lower()
        or "不在" in result.reason
        or "not in" in result.reason.lower()
    )


# ==================================================================
# ToolRegistry risk 仍生效
# ==================================================================

def test_high_risk_tool_flagged():
    """即使工具在 allowed_tools 中，high-risk 状态仍被标记。"""
    desc = _make_descriptor(allowed_tools=("run_shell",))
    registry = _MockToolRegistry().add_tool("run_shell", risk="high", confirmation="always")
    binding = SkillToolBinding(desc, registry)
    result = binding.check("run_shell")
    assert result.allowed is True  # 仍在允许范围内
    assert result.requires_confirmation is True
    assert result.risk_level == "high"


# ==================================================================
# Confirmation 保留
# ==================================================================

def test_confirmation_policy_preserved():
    """Skill 不能降低 ToolRegistry 的 confirmation 要求。"""
    desc = _make_descriptor(allowed_tools=("dangerous_tool",))
    registry = _MockToolRegistry().add_tool("dangerous_tool", confirmation="always")
    binding = SkillToolBinding(desc, registry)
    result = binding.check("dangerous_tool")
    # Skill 不能覆盖 confirmation
    assert result.requires_confirmation is True


# ==================================================================
# Unknown tool blocked
# ==================================================================

def test_unknown_tool_blocked():
    """ToolRegistry 中不存在的工具被阻止。"""
    desc = _make_descriptor(allowed_tools=("nonexistent_tool",))
    registry = _MockToolRegistry()
    binding = SkillToolBinding(desc, registry)
    result = binding.check("nonexistent_tool")
    assert result.allowed is False


# ==================================================================
# Hidden tool 不可暴露
# ==================================================================

def test_hidden_tool_not_exposed():
    """即使 skill 声明了 hidden tool，也不应暴露。"""
    desc = _make_descriptor(allowed_tools=("hidden_tool",))
    registry = _MockToolRegistry().add_tool("hidden_tool", hidden=True)
    binding = SkillToolBinding(desc, registry)
    result = binding.check("hidden_tool")
    assert result.allowed is False


# ==================================================================
# 批量检查
# ==================================================================

def test_check_all_returns_aggregated_result():
    """批量检查应返回每个工具的绑定结果。"""
    desc = _make_descriptor(allowed_tools=("read_file", "write_file", "run_shell"))
    registry = (_MockToolRegistry()
                .add_tool("read_file")
                .add_tool("write_file")
                .add_tool("run_shell", risk="high", confirmation="always"))
    binding = SkillToolBinding(desc, registry)
    results = binding.check_all()
    assert "read_file" in results
    assert "write_file" in results
    assert "run_shell" in results
    assert all(isinstance(r, ToolBindingResult) for r in results.values())


# ==================================================================
# 空 allowed_tools
# ==================================================================

def test_empty_allowed_tools_blocks_all():
    """allowed_tools 为空时，所有工具请求被阻止。"""
    desc = _make_descriptor(allowed_tools=())
    registry = _MockToolRegistry().add_tool("read_file")
    binding = SkillToolBinding(desc, registry)
    result = binding.check("read_file")
    assert result.allowed is False


# ==================================================================
# 便捷函数 validate_tool_request
# ==================================================================

def test_validate_tool_request_convenience():
    """便捷函数应返回 ToolBindingResult。"""
    desc = _make_descriptor(allowed_tools=("read_file",))
    registry = _MockToolRegistry().add_tool("read_file")
    result = validate_tool_request(desc, "read_file", registry)
    assert isinstance(result, ToolBindingResult)
    assert result.allowed is True


# ==================================================================
# ToolBindingResult 结构
# ==================================================================

def test_tool_binding_result_fields():
    """验证 ToolBindingResult 各字段。"""
    result = ToolBindingResult(
        tool_name="read_file",
        allowed=True,
        risk_level="low",
        requires_confirmation=False,
        reason="ok",
    )
    assert result.tool_name == "read_file"
    assert result.allowed is True


# ==================================================================
# 确认不 import legacy
# ==================================================================

def test_tool_binding_module_does_not_import_legacy():
    """tool_binding.py 不能 import agent.skills / agent.legacy_skills。"""
    import ast
    from pathlib import Path

    binding_path = (
        Path(__file__).resolve().parents[1] / "agent" / "skill_system" / "tool_binding.py"
    )
    tree = ast.parse(binding_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("agent.skills")
                assert not alias.name.startswith("agent.legacy_skills")
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("agent.skills")
            assert not node.module.startswith("agent.legacy_skills")
