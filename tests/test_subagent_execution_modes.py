"""SubAgent Phase 5: Execution Mode Policy tests."""

from __future__ import annotations

import pytest

from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.errors import SubAgentModeError
from agent.subagent_system.execution_mode import SubAgentExecutionMode
from agent.subagent_system.policy import SubAgentPolicy, select_execution_mode
from agent.subagent_system.request import SubAgentRequest


def test_default_policy_is_l0_safe_local() -> None:
    """默认 policy 必须关闭真实 LLM、sandbox、worktree 和 nested delegation。"""

    policy = SubAgentPolicy()

    assert policy.local_only is True
    assert policy.default_mode == "local_fake"
    assert policy.real_llm_readonly_allowed is False
    assert policy.real_llm_tool_requesting_allowed is False
    assert policy.sandboxed_tool_capable_allowed is False
    assert policy.external_process_allowed is False
    assert policy.worktree_isolation_allowed is False
    assert policy.max_nested_depth == 0


def test_select_execution_mode_allows_descriptor_bounded_local_mode() -> None:
    """Parent 可选择 descriptor 支持的 L0 mode；SubAgent 不能自行升级。"""

    descriptor = SubAgentDescriptor(
        name="reviewer",
        description="Review",
        role="reviewer",
        supported_modes=("local_fake", "local_deterministic"),
    )
    request = SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file",),
        execution_mode="local_deterministic",
        parent_trace_id="trace-1",
        delegation_reason="review",
    )

    assert (
        select_execution_mode(request, descriptor, SubAgentPolicy())
        == SubAgentExecutionMode.LOCAL_DETERMINISTIC
    )


def test_gated_modes_are_blocked_when_config_gate_is_closed() -> None:
    """L1/L2/L3 contract 可以存在，但 closed gate 时不能执行。"""

    descriptor = SubAgentDescriptor(
        name="reviewer",
        description="Review",
        role="reviewer",
        supported_modes=("local_fake", "real_llm_readonly", "real_llm_tool_requesting"),
    )
    request = SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file",),
        execution_mode="real_llm_readonly",
        parent_trace_id="trace-1",
        delegation_reason="review",
    )

    with pytest.raises(SubAgentModeError):
        select_execution_mode(request, descriptor, SubAgentPolicy())


def test_mode_not_declared_by_descriptor_is_rejected() -> None:
    """descriptor.supported_modes 是 parent selection 的上限。"""

    descriptor = SubAgentDescriptor(
        name="reviewer",
        description="Review",
        role="reviewer",
        supported_modes=("local_fake",),
    )
    request = SubAgentRequest(
        task="Review",
        role="reviewer",
        allowed_tools=("read_file",),
        execution_mode="local_deterministic",
        parent_trace_id="trace-1",
        delegation_reason="review",
    )

    with pytest.raises(SubAgentModeError):
        select_execution_mode(request, descriptor, SubAgentPolicy())

