"""RED guardrails for Sub-agent v0 bounded context behavior."""

from __future__ import annotations

import json

import pytest

from agent.runtime_integration.phase1_hook import build_phase1_dispatcher
from agent.runtime_integration.schema import RuntimeActionRequest, RuntimeActionType
from tests.runtime_integration import subagent_v0_contract_helpers as v0_contract
from tests.runtime_integration.subagent_v0_contract_helpers import (
    build_v0_context,
    route_v0,
)


def test_v0_context_contract_helper_uses_read_seam_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_reader = v0_contract.read_v0_context_file

    def spy_reader(file_id: str, parent_context_blobs: dict[str, str]) -> str:
        calls.append(file_id)
        return original_reader(file_id, parent_context_blobs)

    monkeypatch.setattr(v0_contract, "read_v0_context_file", spy_reader)

    context = build_v0_context({
        "parent_selected_files": ("a.py", "b.py"),
        "child_requested_files": ("child-added.py",),
        "parent_context_blobs": {
            "a.py": "safe parent content that must be truncated",
            "b.py": "safe second parent content",
            "child-added.py": "RAW_CHILD_CONTEXT_SHOULD_NOT_LEAK",
        },
        "max_context_chars": 20,
        "max_files": 1,
    })
    metadata = context["metadata"]

    assert calls == ["a.py"]
    assert metadata["context_file_count"] == 1
    assert metadata["context_length"] <= 20
    assert metadata["selected_file_ids"] == ("a.py",)
    assert "child-added.py" not in metadata["selected_file_ids"]


def test_v0_context_contract_helper_redacts_raw_path_from_metadata() -> None:
    context = build_v0_context({
        "parent_context_blobs": {
            "/tmp/RAW_PATH_SHOULD_NOT_LEAK.py": "RAW_CONTEXT_SHOULD_NOT_LEAK"
        },
    })
    serialized = json.dumps(context["metadata"], default=str)

    assert "RAW_PATH_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized


def test_context_uses_parent_selected_files_and_enforces_limits() -> None:
    result = route_v0(payload={
        "parent_selected_files": ("a.py", "b.py"),
        "child_requested_files": ("c.py",),
        "max_context_chars": 20,
        "max_files": 1,
    })
    context_metadata = result.evidence["context_metadata"]

    assert context_metadata["context_file_count"] == 1
    assert context_metadata["context_length"] <= 20
    assert context_metadata["selected_file_ids"] == ("a.py",)
    assert "c.py" not in context_metadata["selected_file_ids"]


def test_route_v0_context_builder_uses_contract_read_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original_reader = v0_contract.read_v0_context_file

    def spy_reader(file_id: str, parent_context_blobs: dict[str, str]) -> str:
        calls.append(file_id)
        return original_reader(file_id, parent_context_blobs)

    monkeypatch.setattr(v0_contract, "read_v0_context_file", spy_reader)

    result = route_v0(payload={
        "parent_selected_files": ("a.py",),
        "parent_context_blobs": {"a.py": "safe parent-provided content"},
    })

    assert calls == ["a.py"]
    assert result.evidence["context_metadata"]["context_read_seam_calls"] == 1


def test_no_uncontrolled_path_read_text_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    allowed_file_ids = {"a.py"}
    calls: list[str] = []
    original_reader = v0_contract.read_v0_context_file

    def parent_selected_reader(file_id: str, parent_context_blobs: dict[str, str]) -> str:
        assert file_id in allowed_file_ids, (
            "v0 context path must not read child-requested files"
        )
        calls.append(file_id)
        return original_reader(file_id, parent_context_blobs)

    monkeypatch.setattr(v0_contract, "read_v0_context_file", parent_selected_reader)

    result = route_v0(payload={
        "parent_selected_files": ("a.py",),
        "parent_context_blobs": {
            "a.py": "safe parent-provided content",
            "child-added.py": "RAW_CHILD_CONTEXT_SHOULD_NOT_LEAK",
        },
        "child_requested_files": ("child-added.py",),
    })

    assert calls == ["a.py"]
    assert result.evidence["uncontrolled_path_read_text_calls"] == 0
    assert result.evidence["parent_policy_selects_all_files"] is True


def test_context_evidence_contains_only_hash_length_count_and_no_raw_path_or_text() -> None:
    result = route_v0(payload={
        "parent_context_blobs": {
            "/tmp/RAW_PATH_SHOULD_NOT_LEAK.py": "RAW_CONTEXT_SHOULD_NOT_LEAK"
        },
    })
    metadata = result.evidence["context_metadata"]
    serialized = json.dumps(metadata, default=str)

    assert {"context_hash", "context_length", "context_file_count"} <= set(metadata)
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_PATH_SHOULD_NOT_LEAK" not in serialized
    assert "raw_context" not in metadata
    assert "path" not in metadata


def test_child_cannot_add_files_or_mutate_parent_context_prompt_or_messages() -> None:
    parent_state = {
        "context_files": ("parent.py",),
        "context": {"safe": True},
        "prompt": "parent prompt",
        "messages": (),
    }
    before = repr(parent_state)

    result = route_v0(payload={
        "parent_state": parent_state,
        "child_requested_files": ("child-added.py",),
        "child_prompt_patch": "RAW_PROMPT_PATCH",
        "child_message": {"role": "assistant", "content": "RAW_CHILD_OUTPUT"},
    })

    assert result.status in {"failed", "policy_blocked"}
    assert repr(parent_state) == before
    assert result.evidence["context_mutated"] is False
    assert result.evidence["prompt_mutated"] is False
    assert result.evidence["messages_mutated"] is False


def _direct_v0_request(payload: dict[str, object]) -> RuntimeActionRequest:
    return RuntimeActionRequest(
        action_type=RuntimeActionType.SUBAGENT_DELEGATE_V0,
        source="subagent-v0-context-gate-test",
        parent_trace_id="parent-trace",
        payload={
            "profile_id": "default-v0",
            "provider_mode": "fake_local",
            "task": "summarize safely",
            **payload,
        },
    )


def _assert_provider_not_called_for_context_gate(result: object) -> None:
    event_names = set(result.evidence["lifecycle_events"])
    lifecycle_payload_events = {
        str(event.get("event") or "")
        for event in result.evidence.get("lifecycle_event_payloads", ())
    }
    action_log_events = {
        str(event.get("event") or "")
        for event in result.evidence.get("action_log", ())
    }

    assert result.status in {"failed", "policy_blocked"}
    assert result.evidence["provider_called"] is False
    assert result.evidence["provider_completed"] is False
    assert "subagent.context.built" not in event_names
    assert "subagent.context.built" not in lifecycle_payload_events
    assert "subagent.context.built" not in action_log_events
    assert "subagent.provider.called" not in event_names
    assert "subagent.provider.completed" not in event_names
    assert "subagent.execution.failed" in event_names


def test_missing_prepared_context_fails_closed_before_provider_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_V0)

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provider adapter must not run without bounded context")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    result = dispatcher.route(_direct_v0_request({}))

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_missing"
    assert result.evidence["context_missing"] is True
    assert result.evidence["context_not_built"] is True


def test_empty_context_hash_fails_closed_before_provider_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_V0)

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provider adapter must not run with empty context_hash")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    result = dispatcher.route(_direct_v0_request({
        "prepared_v0_context": {
            "metadata": {
                "context_hash": "",
                "context_length": 1,
                "context_file_count": 1,
                "max_context_chars": 10,
                "max_files": 1,
            },
        },
    }))

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_hash_missing"


def test_context_limits_fail_closed_before_provider_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatcher = build_phase1_dispatcher()
    handler = dispatcher.get_handler(RuntimeActionType.SUBAGENT_DELEGATE_V0)

    def forbidden_provider_call(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provider adapter must not run when bounded context exceeds limits")

    monkeypatch.setattr(handler, "_call_v0_provider_adapter", forbidden_provider_call)
    too_long = dispatcher.route(_direct_v0_request({
        "profile_contract": {"max_context_chars": 10, "max_files": 2},
        "prepared_v0_context": {
            "metadata": {
                "context_hash": "ctx-safe-hash",
                "context_length": 11,
                "context_file_count": 1,
                "max_context_chars": 10,
                "max_files": 2,
                "raw_context": "RAW_CONTEXT_SHOULD_NOT_LEAK",
                "path": "/tmp/raw-context-path.txt",
            },
        },
    }))
    too_many_files = dispatcher.route(_direct_v0_request({
        "profile_contract": {"max_context_chars": 100, "max_files": 1},
        "prepared_v0_context": {
            "metadata": {
                "context_hash": "ctx-safe-hash",
                "context_length": 10,
                "context_file_count": 2,
                "max_context_chars": 100,
                "max_files": 1,
            },
        },
    }))

    _assert_provider_not_called_for_context_gate(too_long)
    _assert_provider_not_called_for_context_gate(too_many_files)
    assert too_long.evidence["failure_kind"] == "context_length_exceeds_limit"
    assert too_many_files.evidence["failure_kind"] == "context_file_count_exceeds_limit"
    serialized = json.dumps({
        "too_long": too_long.evidence,
        "too_many": too_many_files.evidence,
    }, default=str)
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized
    assert "/tmp/raw-context-path.txt" not in serialized


def test_tool_use_provider_output_without_prepared_context_fails_closed() -> None:
    dispatcher = build_phase1_dispatcher()
    result = dispatcher.route(_direct_v0_request({
        "provider_output": {
            "type": "tool_use",
            "name": "sk-live-tool-RAW",
            "reason": "RAW_TOOL_REASON_SHOULD_NOT_LEAK",
            "input": {"path": "/tmp/RAW_TOOL_PATH_SHOULD_NOT_LEAK"},
        },
    }))
    serialized = json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
    }, default=str)

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_missing"
    assert result.payload.get("needs_parent_tool_request") is not True
    assert "subagent.result.produced" not in set(result.evidence["lifecycle_events"])
    assert "subagent.parent_decision.pending" not in set(result.evidence["lifecycle_events"])
    assert "RAW_TOOL_REASON_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_TOOL_PATH_SHOULD_NOT_LEAK" not in serialized
    assert "sk-live-tool-RAW" not in serialized


def test_child_result_without_prepared_context_does_not_enter_parent_decision() -> None:
    dispatcher = build_phase1_dispatcher()
    result = dispatcher.route(_direct_v0_request({
        "child_result": {
            "summary": "RAW_CHILD_RESULT_SHOULD_NOT_LEAK",
            "path": "/tmp/RAW_CHILD_PATH_SHOULD_NOT_LEAK",
        },
    }))
    event_names = set(result.evidence["lifecycle_events"])
    serialized = json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
    }, default=str)

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_missing"
    assert "subagent.result.produced" not in event_names
    assert "subagent.parent_decision.pending" not in event_names
    assert result.payload.get("parent_decision_status") != "pending"
    assert "RAW_CHILD_RESULT_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_CHILD_PATH_SHOULD_NOT_LEAK" not in serialized


def test_batch_memory_provider_output_without_prepared_context_fails_closed() -> None:
    dispatcher = build_phase1_dispatcher()
    result = dispatcher.route(_direct_v0_request({
        "provider_output": {
            "batch_memory": [{
                "key": "raw",
                "value": "RAW_MEMORY_SHOULD_NOT_LEAK",
                "path": "/tmp/RAW_MEMORY_PATH_SHOULD_NOT_LEAK",
            }],
        },
    }))
    serialized = json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
    }, default=str)

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_missing"
    assert result.evidence["batch_memory_seen"] is False
    assert "subagent.result.produced" not in set(result.evidence["lifecycle_events"])
    assert "RAW_MEMORY_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_MEMORY_PATH_SHOULD_NOT_LEAK" not in serialized


def test_lifecycle_catalog_introspection_without_prepared_context_fails_closed() -> None:
    dispatcher = build_phase1_dispatcher()
    result = dispatcher.route(_direct_v0_request({
        "introspect_lifecycle_catalog": True,
        "raw_context": "RAW_CONTEXT_SHOULD_NOT_LEAK",
        "raw_path": "/tmp/RAW_CONTEXT_PATH_SHOULD_NOT_LEAK",
        "secret": "sk-test-context-secret",
    }))
    event_names = set(result.evidence["lifecycle_events"])
    serialized = json.dumps({
        "payload": result.payload,
        "evidence": result.evidence,
    }, default=str)

    _assert_provider_not_called_for_context_gate(result)
    assert result.evidence["failure_kind"] == "context_missing"
    assert result.payload.get("parent_decision_status") != "pending"
    assert "subagent.context.built" not in event_names
    assert "subagent.result.produced" not in event_names
    assert "subagent.parent_decision.pending" not in event_names
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_CONTEXT_PATH_SHOULD_NOT_LEAK" not in serialized
    assert "sk-test-context-secret" not in serialized
