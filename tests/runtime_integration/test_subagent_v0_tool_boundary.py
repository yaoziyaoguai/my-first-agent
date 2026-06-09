"""RED guardrails for Sub-agent v0 child tool boundaries."""

from __future__ import annotations

import inspect

import pytest


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 tool gate not implemented yet")
def test_child_tools_are_disabled_by_default() -> None:
    from agent.runtime_integration import subagent_action

    profile = subagent_action.default_subagent_v0_profile()

    assert profile.allowed_tools == ()
    assert profile.can_use_tools is False


@pytest.mark.xfail(strict=True, reason="V0 tool_use sanitizer not implemented yet")
def test_tool_use_becomes_parent_tool_request_metadata_not_execution() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.parse_subagent_v0_provider_output({
        "tool_use": {
            "name": "read_file",
            "input": {"path": "RAW_PATH_SHOULD_NOT_EXECUTE"},
            "reason": "needs context",
        },
    })

    assert result.needs_parent_tool_request is True
    assert result.requested_tool_name == "read_file"
    assert result.safe_arguments_metadata
    assert result.tool_executed is False
    assert "RAW_PATH_SHOULD_NOT_EXECUTE" not in repr(result.safe_arguments_metadata)


@pytest.mark.xfail(strict=True, reason="V0 unauthorized tool fail-closed path not implemented yet")
def test_unauthorized_tool_request_fails_closed_without_parent_state_mutation() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.handle_subagent_v0_tool_request(
        requested_tool_name="shell",
        requested_arguments={"cmd": "echo should-not-run"},
        profile=subagent_action.default_subagent_v0_profile(),
    )

    assert result.status in {"policy_blocked", "failed"}
    assert result.tool_executed is False
    assert result.parent_messages_mutated is False
    assert result.parent_checkpoint_mutated is False


@pytest.mark.xfail(strict=True, reason="SubAgentV0Handler not implemented yet")
def test_v0_child_path_cannot_call_direct_tool_execution_apis() -> None:
    from agent.runtime_integration import subagent_action

    source = inspect.getsource(subagent_action.SubAgentV0Handler)

    forbidden = (
        "execute_single_tool",
        "ToolRuntimeMediator.execute",
        "subprocess",
        "requests.",
        "Path.write_text",
        "open(",
        "shell",
        "bash",
    )
    for token in forbidden:
        assert token not in source


@pytest.mark.xfail(strict=True, reason="Child tool result checkpoint isolation not implemented yet")
def test_child_tool_result_cannot_enter_parent_messages_or_checkpoint() -> None:
    from agent.runtime_integration import subagent_action

    state = subagent_action.simulate_subagent_v0_tool_result_boundary(
        raw_tool_result="RAW_TOOL_RESULT_SHOULD_NOT_LEAK",
    )

    assert "RAW_TOOL_RESULT_SHOULD_NOT_LEAK" not in repr(state.parent_messages)
    assert "RAW_TOOL_RESULT_SHOULD_NOT_LEAK" not in repr(state.parent_checkpoint)
    assert state.child_scratch_metadata["tool_result_hash"]
