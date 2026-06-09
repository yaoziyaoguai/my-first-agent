"""RED guardrails for Sub-agent v0 child tool boundaries."""

from __future__ import annotations

import json

import pytest

from tests.runtime_integration.subagent_v0_contract_helpers import route_v0


def test_child_tools_are_disabled_by_default() -> None:
    result = route_v0()
    evidence = dict(result.evidence)

    assert evidence["allowed_tool_count"] == 0
    assert evidence["can_use_tools"] is False


def test_tool_use_becomes_parent_tool_request_metadata_not_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.tool_executor as tool_executor
    import agent.tool_runtime_mediator as tool_runtime_mediator

    def forbidden_execute(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("v0 child tool_use executed a parent tool")

    monkeypatch.setattr(tool_executor, "execute_single_tool", forbidden_execute)
    monkeypatch.setattr(tool_runtime_mediator, "execute_single_tool", forbidden_execute)
    result = route_v0(payload={
        "provider_output": {
            "type": "tool_use",
            "name": "read_file",
            "input": {"path": "RAW_PATH_SHOULD_NOT_EXECUTE"},
            "reason": "needs context",
        },
    })
    evidence = dict(result.evidence)

    assert result.payload["needs_parent_tool_request"] is True
    assert result.payload["requested_tool_name"] == "read_file"
    assert result.payload["safe_arguments_metadata"]
    assert evidence["tool_executed"] is False
    assert "RAW_PATH_SHOULD_NOT_EXECUTE" not in repr(result.payload["safe_arguments_metadata"])
    assert "requested_tool_reason" not in result.payload


def test_provider_tool_reason_and_arguments_are_sanitized_not_returned_raw() -> None:
    result = route_v0(payload={
        "provider_output": {
            "type": "tool_use",
            "name": "read_file",
            "input": {
                "path": "/tmp/raw-tool-arg-path.txt",
                "api_key": "tool-arg-secret",
            },
            "reason": (
                "RAW_TOOL_REASON_SHOULD_NOT_LEAK "
                "RAW_PROMPT_SHOULD_NOT_LEAK /tmp/raw-tool-reason-path.txt"
            ),
        },
    })

    assert result.payload["needs_parent_tool_request"] is True
    assert result.payload["requested_tool_name"] == "read_file"
    assert "requested_tool_reason" not in result.payload
    reason_metadata = result.payload["requested_tool_reason_metadata"]
    assert reason_metadata["requested_tool_reason_present"] is True
    assert reason_metadata["requested_tool_reason_length"] > 0
    assert reason_metadata["requested_tool_reason_hash"]
    assert reason_metadata["requested_tool_reason_redacted"] is True
    args_metadata = result.payload["safe_arguments_metadata"]
    assert args_metadata["argument_count"] == 2
    assert args_metadata["args_key_count"] == 2
    assert args_metadata["args_keys_hash"]
    assert "argument_keys" not in args_metadata
    assert args_metadata["arguments_hash"]
    assert args_metadata["redacted"] is True

    serialized = json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
    }, default=str)
    forbidden = (
        "RAW_TOOL_REASON_SHOULD_NOT_LEAK",
        "RAW_PROMPT_SHOULD_NOT_LEAK",
        "/tmp/raw-tool-reason-path.txt",
        "/tmp/raw-tool-arg-path.txt",
        "tool-arg-secret",
    )
    for token in forbidden:
        assert token not in serialized


def test_unauthorized_tool_request_fails_closed_without_parent_state_mutation() -> None:
    result = route_v0(payload={
        "provider_output": {
            "type": "tool_use",
            "name": "shell",
            "input": {"cmd": "echo should-not-run"},
        },
    })
    evidence = dict(result.evidence)

    assert result.status in {"policy_blocked", "failed"}
    assert evidence["tool_executed"] is False
    assert evidence["parent_messages_mutated"] is False
    assert evidence["parent_checkpoint_mutated"] is False


def test_v0_child_path_cannot_call_direct_tool_execution_apis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.tool_executor as tool_executor
    import agent.tool_runtime_mediator as tool_runtime_mediator

    def forbidden_execute(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("direct parent tool execution API was called")

    monkeypatch.setattr(tool_executor, "execute_single_tool", forbidden_execute)
    monkeypatch.setattr(tool_runtime_mediator, "execute_single_tool", forbidden_execute)

    result = route_v0(payload={
        "provider_output": {
            "type": "tool_use",
            "name": "read_file",
            "input": {"path": "file.txt"},
        },
    })

    assert result.payload["needs_parent_tool_request"] is True
    assert result.evidence["tool_executed"] is False


def test_child_tool_result_cannot_enter_parent_messages_or_checkpoint() -> None:
    result = route_v0(payload={
        "raw_child_tool_result": "RAW_TOOL_RESULT_SHOULD_NOT_LEAK",
    })
    surfaces = {
        "parent_messages": result.evidence.get("parent_messages", ()),
        "parent_checkpoint": result.evidence.get("parent_checkpoint", {}),
        "checkpoint_metadata": result.evidence.get("checkpoint_metadata", {}),
    }

    assert result.evidence["tool_result_hash"]
    assert "RAW_TOOL_RESULT_SHOULD_NOT_LEAK" not in repr(surfaces)
