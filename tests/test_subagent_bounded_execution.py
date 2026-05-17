"""SubAgent Phase 10: Bounded Local Execution tests."""

from __future__ import annotations

from agent.subagent_system.context import build_context_package
from agent.subagent_system.descriptor import SubAgentDescriptor
from agent.subagent_system.executor import execute_local
from agent.subagent_system.request import SubAgentRequest


def _package(max_iterations: int = 1, task: str = "Review code"):
    descriptor = SubAgentDescriptor(name="reviewer", description="Review", role="reviewer")
    request = SubAgentRequest(
        task=task,
        role="reviewer",
        allowed_tools=("read_file",),
        max_iterations=max_iterations,
        parent_trace_id="trace-1",
        delegation_reason="review",
    )
    return build_context_package(request=request, descriptor=descriptor, tool_snapshots=())


def test_local_executor_completes_fake_delegation_without_provider_or_tools() -> None:
    """L0 executor 只产出 deterministic result，不调用真实 LLM 或工具。"""

    result = execute_local(_package(max_iterations=2))

    assert result.status == "ok"
    assert result.stop_reason == "task_completed"
    assert result.audit.iterations_used == 1
    assert result.audit.tools_executed == ()
    assert "deterministic" in result.summary


def test_local_executor_enforces_max_iterations_hard_stop() -> None:
    """max_iterations 是硬边界，不能静默超出。"""

    result = execute_local(_package(max_iterations=1, task="loop until max"))

    assert result.status == "max_iterations_exceeded"
    assert result.stop_reason == "max_iterations_exceeded"
    assert result.audit.iterations_used == 1
    assert result.audit.max_iterations == 1


def test_local_executor_can_emit_clarification_and_policy_stops() -> None:
    """L0 需要能表达主要 stop reason，但仍不执行副作用。"""

    clarification = execute_local(_package(task="needs clarification"))
    blocked = execute_local(_package(task="request shell_exec"))

    assert clarification.stop_reason == "needs_clarification"
    assert clarification.clarification_question
    assert blocked.stop_reason == "policy_blocked"
    assert "shell" in blocked.warnings[0]

