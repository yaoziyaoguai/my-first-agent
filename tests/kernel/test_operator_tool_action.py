from __future__ import annotations

from dataclasses import replace

import pytest

from agent.runtime.contracts import (
    ActiveRun,
    ExecuteOperatorTool,
    InvocationOrigin,
)
from agent.runtime.state import accept_action
from tests.kernel.fakes import conversation_with_active_goal


def _action(state, **overrides):
    values = {
        "conversation_id": state.conversation_id,
        "action_seq": state.next_action_seq,
        "expected_revision": state.revision,
        "action_id": "operator-action-1",
        "tool_name": "skill_package_stage",
        "arguments": {"source": {"kind": "local", "path": "private/source.skillpkg"}},
        "submitted_at": "2026-08-30T12:00:00Z",
    }
    values.update(overrides)
    return ExecuteOperatorTool(**values)


def test_action_recursively_freezes_arguments() -> None:
    state = conversation_with_active_goal()
    action = _action(state)
    with pytest.raises(TypeError, match="frozen"):
        action.arguments["source"]["path"] = "changed"


@pytest.mark.parametrize("field,value", [
    ("action_id", ""),
    ("tool_name", "bad name"),
    ("submitted_at", "not-a-time"),
])
def test_action_rejects_open_string_shapes(field, value) -> None:
    state = conversation_with_active_goal()
    with pytest.raises(ValueError):
        _action(state, **{field: value})


def test_operator_action_requires_existing_idle_active_run_and_goal() -> None:
    state = conversation_with_active_goal()
    assert accept_action(state, _action(state)).reason == "operator_tool_requires_active_run"
    ready = replace(state, active_run=ActiveRun(run_id="run-existing"))
    transition = accept_action(ready, _action(ready))
    assert transition.reason is None
    assert transition.state.active_run.invocation_origin is InvocationOrigin.OPERATOR
    assert transition.state.active_run.tool_calls[0].tool_call_id == "operator-action-1"
