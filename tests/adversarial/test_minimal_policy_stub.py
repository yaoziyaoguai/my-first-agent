"""GE-1 C1: 最小 adversarial stub，不执行任何真实危险动作。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "golden_e2e"
    / "fixtures"
    / "adversarial_stub.json"
)


def test_ge1_c1_forbidden_tool_name_fails_closed_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """安全 stub 使用空参数请求 forbidden tool，验证 policy fail-closed。"""
    import agent.tool_runtime_mediator as mediator_module
    from agent import logger
    from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
    from agent.runtime_integration.schema import RuntimeActionType
    from agent.state import create_agent_state
    from agent.tool_executor import FORCE_STOP
    from agent.tool_runtime_mediator import ToolRuntimeMediator

    monkeypatch.setattr(logger, "log_event", lambda *args, **kwargs: None)

    def _must_not_execute(*args, **kwargs):
        raise AssertionError("forbidden adversarial stub must not execute")

    monkeypatch.setattr(mediator_module, "execute_single_tool", _must_not_execute)

    state = create_agent_state(system_prompt="golden-adversarial")
    state.task.status = "running"
    dispatcher = build_phase1_dispatcher()
    mediator = ToolRuntimeMediator(
        dispatcher,
        state=state,
        turn_state=SimpleNamespace(on_display_event=None, round_tool_traces=[]),
        turn_context={},
        messages=[],
    )
    result = mediator.mediate(
        SimpleNamespace(name="shell", input={}, id="ge1-adversarial-stub")
    )

    gate_event = next(
        event
        for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_GATE
    )
    invoke_events = [
        event
        for event in dispatcher.action_log
        if event.action_type == RuntimeActionType.TOOL_INVOKE
    ]
    actual = {
        "input_kind": "forbidden_tool_name_safe_stub",
        "mediator_result": result,
        "force_stop": FORCE_STOP,
        "gate_status": gate_event.status,
        "rejection_reason": gate_event.evidence.get("rejection_reason"),
        "dangerous_tool_function_invoked": gate_event.evidence.get(
            "dangerous_tool_function_invoked"
        ),
        "tool_invoke_event_count": len(invoke_events),
    }

    assert FIXTURE_PATH.is_file(), f"missing golden fixture: {FIXTURE_PATH}"
    expected = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert actual == expected
