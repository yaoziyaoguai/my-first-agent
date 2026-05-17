"""SubAgent Phase 3: Delegation Contract Types tests.

Contract 层只定义不可变 request/result/audit/run 类型和枚举：
- 不执行工具；
- 不调用 provider；
- 不写 Memory；
- 不拥有 Runtime loop。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agent.subagent_system.execution_mode import (
    SubAgentExecutionMode,
    SubAgentStopReason,
)
from agent.subagent_system.request import SubAgentRequest
from agent.subagent_system.result import (
    ParentAdjudicationResult,
    SubAgentAuditRecord,
    SubAgentResult,
    SubAgentRun,
    ToolRequest,
)


def _request() -> SubAgentRequest:
    return SubAgentRequest(
        task="Review this change",
        role="reviewer",
        allowed_tools=("read_file",),
        parent_trace_id="trace-1",
        delegation_reason="parallel review",
    )


def test_execution_mode_and_stop_reason_enums_cover_rfc_values() -> None:
    """枚举值是 cross-module contract，后续 phase 只能引用不能自造字符串。"""

    assert {mode.value for mode in SubAgentExecutionMode} == {
        "local_fake",
        "local_deterministic",
        "real_llm_readonly",
        "real_llm_tool_requesting",
        "sandboxed_tool_capable",
    }
    assert {reason.value for reason in SubAgentStopReason} == {
        "task_completed",
        "task_completed_low_confidence",
        "max_iterations_exceeded",
        "max_context_exceeded",
        "needs_clarification",
        "needs_confirmation",
        "tool_blocked",
        "policy_blocked",
        "error",
        "interrupted",
    }


def test_subagent_request_defaults_are_l0_safe_and_frozen() -> None:
    """Parent 创建 request；默认 execution mode 必须保持 L0 local_fake。"""

    request = _request()

    assert request.execution_mode == "local_fake"
    assert request.memory_scope == "none"
    assert request.max_iterations == 1
    assert request.max_revisions == 1
    assert request.allowed_skills == ()
    with pytest.raises(FrozenInstanceError):
        request.task = "mutated"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"task": ""}, "task"),
        ({"role": ""}, "role"),
        ({"allowed_tools": ["read_file"]}, "allowed_tools"),
        ({"max_iterations": 0}, "max_iterations"),
        ({"execution_mode": "real_llm"}, "execution_mode"),
        ({"max_revisions": -1}, "max_revisions"),
    ],
)
def test_subagent_request_validation_fails_closed(kwargs: dict[str, object], message: str) -> None:
    """无效 request 不应延迟到 executor 才失败。"""

    data = {
        "task": "Review",
        "role": "reviewer",
        "allowed_tools": ("read_file",),
        "parent_trace_id": "trace-1",
        "delegation_reason": "review",
    }
    data.update(kwargs)

    with pytest.raises(ValueError, match=message):
        SubAgentRequest(**data)  # type: ignore[arg-type]


def test_result_audit_run_and_adjudication_contracts_are_frozen() -> None:
    """result → audit → adjudication 是 parent-controlled handoff contract。"""

    audit = SubAgentAuditRecord(
        subagent_name="code-reviewer",
        delegation_id="delegation-1",
        parent_trace_id="trace-1",
        execution_mode="local_fake",
        status="ok",
        stop_reason="task_completed",
        iterations_used=1,
        max_iterations=1,
        tools_requested=("read_file",),
        tools_denied=(),
        tools_executed=(),
        memory_proposals_count=0,
        warnings=(),
        confidence=0.8,
        elapsed_ms=1,
        revision_count=0,
        trace_event_count=0,
    )
    result = SubAgentResult(
        status="ok",
        summary="Looks safe.",
        artifacts=(),
        tool_requests=(ToolRequest("read_file", {"path": "x.py"}, "inspect", "low"),),
        memory_proposals=(),
        confidence=0.8,
        warnings=(),
        audit=audit,
        handoff_back="Parent should decide.",
        clarification_question=None,
        trace_events=(),
        stop_reason="task_completed",
    )
    adjudication = ParentAdjudicationResult.accept("good", merged_summary=result.summary)
    run = SubAgentRun(
        delegation_id="delegation-1",
        state="completed",
        request=_request(),
        descriptor=None,
        context_package=None,
        result=result,
        adjudication=adjudication,
        revision_count=0,
    )

    assert adjudication.action == "accept_result"
    assert run.result is result
    with pytest.raises(FrozenInstanceError):
        result.summary = "mutated"  # type: ignore[misc]

