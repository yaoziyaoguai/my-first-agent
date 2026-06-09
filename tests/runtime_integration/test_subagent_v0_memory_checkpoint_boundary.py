"""RED guardrails for Sub-agent v0 memory and checkpoint boundaries."""

from __future__ import annotations

import inspect

import pytest

from agent.subagent_system import executor
from tests.runtime_integration.subagent_v0_contract_helpers import V0_XFAIL, route_v0


@pytest.mark.xfail(**V0_XFAIL)
def test_v0_profile_cannot_write_memory_checkpoint_or_emit_memory_requests() -> None:
    result = route_v0()
    evidence = dict(result.evidence)

    assert evidence["can_write_memory"] is False
    assert evidence["can_request_memory"] is False
    assert evidence["can_write_checkpoint"] is False
    assert evidence["memory_scope"] == "none"


@pytest.mark.xfail(**V0_XFAIL)
def test_no_batch_memory_pending_memory_proposal_or_direct_write_from_v0_result() -> None:
    result = route_v0(payload={
        "provider_output": {
            "summary": "safe",
            "batch_memory": [{"key": "raw", "value": "RAW_MEMORY", "scope": "project"}],
        },
    })

    assert result.status in {"failed", "policy_blocked"}
    assert result.evidence["batch_memory_seen"] is False
    assert result.evidence["memory_proposals_count"] == 0
    assert result.evidence["pending_memory_proposal_created"] is False
    assert result.evidence["memory_store_write"] is False


@pytest.mark.xfail(**V0_XFAIL)
def test_v0_path_does_not_call_direct_memory_or_checkpoint_write_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import agent.checkpoint as checkpoint
    import agent.memory_runtime as memory_runtime
    from agent.memory_store import InMemoryMemoryStore
    from agent.runtime_integration import checkpoint_save

    def forbidden_write(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("v0 child path attempted memory/checkpoint write")

    monkeypatch.setattr(InMemoryMemoryStore, "apply_candidate", forbidden_write)
    monkeypatch.setattr(memory_runtime.MemoryRuntime, "resolve_confirmation", forbidden_write)
    monkeypatch.setattr(checkpoint, "save_checkpoint", forbidden_write)
    monkeypatch.setattr(checkpoint_save, "save_runtime_checkpoint", forbidden_write)

    result = route_v0(payload={"raw_child_result": "RAW_CHILD_RESULT_SHOULD_NOT_LEAK"})

    assert result.evidence["memory_store_write"] is False
    assert result.evidence["checkpoint_write"] is False


@pytest.mark.xfail(**V0_XFAIL)
def test_parent_checkpoint_stores_safe_subagent_metadata_only() -> None:
    result = route_v0(payload={"raw_child_result": "RAW_CHILD_RESULT_SHOULD_NOT_LEAK"})
    metadata = result.evidence["checkpoint_metadata"]

    assert set(metadata) <= {"delegation_id", "profile_id", "status", "result_hash", "decision"}
    assert "RAW_CHILD_RESULT_SHOULD_NOT_LEAK" not in repr(metadata)
    assert metadata["result_hash"]


def test_existing_l2_executor_still_contains_batch_memory_before_v0_freeze() -> None:
    # Pre-U3A baseline: this documents why U3A must freeze L2 before v0
    # execution starts. Update or delete this baseline after U3A lands.
    source = inspect.getsource(executor.execute_l2)

    assert "batch_memory" in source
    assert "_parse_batch_memory" in source
