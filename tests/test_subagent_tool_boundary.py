"""SubAgent Phase 6: Tool Permission Boundary tests."""

from __future__ import annotations

from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.tool_boundary import SubAgentToolBoundary


TOOL_REGISTRY = {
    "read_file": {
        "name": "read_file",
        "description": "Read file",
        "risk_level": "low",
        "confirmation": "never",
        "meta_tool": False,
    },
    "shell_exec": {
        "name": "shell_exec",
        "description": "Run shell",
        "risk_level": "high",
        "confirmation": "always",
        "meta_tool": False,
    },
    "hidden_debug": {
        "name": "hidden_debug",
        "description": "Internal",
        "risk_level": "high",
        "confirmation": "always",
        "meta_tool": True,
    },
}


def _descriptor() -> SubAgentDescriptor:
    return SubAgentDescriptor(
        name="reviewer",
        description="Review",
        role="reviewer",
        allowed_tools=("read_file", "shell_exec", "hidden_debug"),
    )


def _request() -> SubAgentRequest:
    return SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file", "shell_exec"),
        parent_trace_id="trace-1",
        delegation_reason="review",
    )


def test_tool_boundary_intersects_descriptor_and_request_allowed_tools() -> None:
    """allowed_tools 是上限交集，不是执行授权。"""

    boundary = SubAgentToolBoundary(TOOL_REGISTRY)

    allowed = boundary.check("read_file", {}, _descriptor(), _request())
    denied = boundary.check("grep", {}, _descriptor(), _request())

    assert allowed.allowed is True
    assert allowed.risk_level == "low"
    assert allowed.requires_confirmation is False
    assert denied.allowed is False
    assert denied.deny_reason == "tool_not_allowed"


def test_tool_boundary_preserves_tool_registry_confirmation() -> None:
    """高风险工具即使在 allowlist 中，也仍保留 ToolRegistry confirmation。"""

    boundary = SubAgentToolBoundary(TOOL_REGISTRY)

    result = boundary.check("shell_exec", {}, _descriptor(), _request())

    assert result.allowed is True
    assert result.risk_level == "high"
    assert result.requires_confirmation is True


def test_hidden_internal_tools_are_never_exposed() -> None:
    """hidden/meta tools 不能进入 SubAgent 可见 snapshot。"""

    boundary = SubAgentToolBoundary(TOOL_REGISTRY)

    result = boundary.check("hidden_debug", {}, _descriptor(), _request())
    snapshot = boundary.snapshot(_descriptor(), _request())

    assert result.allowed is False
    assert result.deny_reason == "hidden_tool"
    assert [item.name for item in snapshot] == ["read_file", "shell_exec"]

