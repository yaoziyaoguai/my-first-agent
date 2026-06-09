"""RED guardrails for Sub-agent v0 child tool boundaries."""

from __future__ import annotations

import json

import pytest

from tests.runtime_integration.subagent_v0_contract_helpers import route_v0


def _tool_use_payload(
    *,
    name: str,
    allowed_tools: tuple[str, ...] = (),
    tool_input: dict[str, object] | None = None,
    reason: str = "needs context",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "provider_output": {
            "type": "tool_use",
            "name": name,
            "input": tool_input or {"path": "RAW_PATH_SHOULD_NOT_EXECUTE"},
            "reason": reason,
        },
    }
    if allowed_tools:
        payload["profile_contract"] = {"allowed_tools": allowed_tools}
    return payload


def _serialized_tool_surfaces(result: object) -> str:
    return json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
        "action_log": result.evidence.get("action_log"),
        "log_viewer": result.evidence.get("log_viewer"),
        "checkpoint_metadata": result.evidence.get("checkpoint_metadata"),
    }, default=str)


def _assert_non_allowlisted_tool_name_redacted(raw_tool_name: str) -> None:
    result = route_v0(payload=_tool_use_payload(name=raw_tool_name))

    assert result.payload["needs_parent_tool_request"] is True
    assert result.payload["requested_tool_name"] == ""
    metadata = result.payload["requested_tool_name_metadata"]
    assert metadata["requested_tool_name_present"] is True
    assert metadata["requested_tool_name_length"] == len(raw_tool_name)
    assert metadata["requested_tool_name_hash"]
    assert raw_tool_name not in metadata["requested_tool_name_hash"]
    assert metadata["requested_tool_name_redacted"] is True
    assert metadata["requested_tool_name_allowed"] is False
    assert raw_tool_name not in _serialized_tool_surfaces(result)
    assert result.evidence["tool_executed"] is False


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
    result = route_v0(payload=_tool_use_payload(
        name="read_file",
        allowed_tools=("read_file",),
    ))
    evidence = dict(result.evidence)

    assert result.payload["needs_parent_tool_request"] is True
    assert result.payload["requested_tool_name"] == "read_file"
    assert result.payload["requested_tool_name_metadata"]["requested_tool_name_allowed"] is True
    assert result.payload["requested_tool_name_metadata"]["requested_tool_name_redacted"] is False
    assert result.payload["safe_arguments_metadata"]
    assert evidence["tool_executed"] is False
    assert "RAW_PATH_SHOULD_NOT_EXECUTE" not in repr(result.payload["safe_arguments_metadata"])
    assert "requested_tool_reason" not in result.payload


def test_provider_tool_reason_and_arguments_are_sanitized_not_returned_raw() -> None:
    result = route_v0(payload=_tool_use_payload(
        name="read_file",
        allowed_tools=("read_file",),
        tool_input={
                "path": "/tmp/raw-tool-arg-path.txt",
                "api_key": "tool-arg-secret",
        },
        reason=(
            "RAW_TOOL_REASON_SHOULD_NOT_LEAK "
            "RAW_PROMPT_SHOULD_NOT_LEAK /tmp/raw-tool-reason-path.txt"
        ),
    ))

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


def test_provider_token_like_tool_name_is_redacted_from_result_surfaces() -> None:
    _assert_non_allowlisted_tool_name_redacted("sk-live-abc123")


def test_provider_path_like_tool_name_is_redacted_from_result_surfaces() -> None:
    _assert_non_allowlisted_tool_name_redacted("/tmp/secret/tool")


def test_provider_identifier_like_tool_name_is_redacted_without_allowlist() -> None:
    _assert_non_allowlisted_tool_name_redacted("normal_looking_but_not_allowlisted")


def test_allowlisted_tool_name_can_be_returned_as_safe_parent_identifier() -> None:
    result = route_v0(payload=_tool_use_payload(
        name="read_file",
        allowed_tools=("read_file",),
    ))

    metadata = result.payload["requested_tool_name_metadata"]
    assert result.payload["needs_parent_tool_request"] is True
    assert result.payload["requested_tool_name"] == "read_file"
    assert metadata["requested_tool_name_present"] is True
    assert metadata["requested_tool_name_length"] == len("read_file")
    assert metadata["requested_tool_name_hash"]
    assert "read_file" not in metadata["requested_tool_name_hash"]
    assert metadata["requested_tool_name_redacted"] is False
    assert metadata["requested_tool_name_allowed"] is True
    assert result.evidence["tool_executed"] is False


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

    result = route_v0(payload=_tool_use_payload(
        name="read_file",
        allowed_tools=("read_file",),
        tool_input={"path": "file.txt"},
    ))

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
