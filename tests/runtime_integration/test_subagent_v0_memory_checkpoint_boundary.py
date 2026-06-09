"""RED guardrails for Sub-agent v0 memory and checkpoint boundaries."""

from __future__ import annotations

import inspect

import pytest

from agent.subagent_system import executor


@pytest.mark.xfail(strict=True, reason="V0 memory/checkpoint capability gates not implemented yet")
def test_v0_profile_cannot_write_memory_checkpoint_or_emit_memory_requests() -> None:
    from agent.runtime_integration import subagent_action

    profile = subagent_action.default_subagent_v0_profile()

    assert profile.can_write_memory is False
    assert profile.can_request_memory is False
    assert profile.can_write_checkpoint is False
    assert profile.memory_scope == "none"


@pytest.mark.xfail(strict=True, reason="V0 executor result contract not implemented yet")
def test_no_batch_memory_pending_memory_proposal_or_direct_write_from_v0_result() -> None:
    from agent.runtime_integration import subagent_action

    result = subagent_action.parse_subagent_v0_provider_output({
        "summary": "safe",
        "batch_memory": [{"key": "raw", "value": "RAW_MEMORY", "scope": "project"}],
    })

    assert result.status in {"failed", "policy_blocked"}
    assert result.batch_memory_proposals == ()
    assert result.memory_proposals == ()
    assert result.pending_memory_proposal_path is None
    assert result.memory_store_write is False


@pytest.mark.xfail(strict=True, reason="V0 handler memory/checkpoint isolation not implemented yet")
def test_v0_handler_does_not_call_direct_memory_or_checkpoint_write_paths() -> None:
    from agent.runtime_integration import subagent_action

    source = inspect.getsource(subagent_action.SubAgentV0Handler)

    forbidden = (
        "MemoryStore",
        "direct_write=True",
        "resolve_confirmation(",
        "batch_memory",
        "CheckpointSaveHandler",
        "checkpoint.write",
        "write_text(",
    )
    for token in forbidden:
        assert token not in source


@pytest.mark.xfail(strict=True, reason="V0 checkpoint-safe metadata contract not implemented yet")
def test_parent_checkpoint_stores_safe_subagent_metadata_only() -> None:
    from agent.runtime_integration import subagent_action

    metadata = subagent_action.safe_subagent_v0_checkpoint_metadata(
        raw_child_result="RAW_CHILD_RESULT_SHOULD_NOT_LEAK",
    )

    assert set(metadata) <= {"delegation_id", "profile_id", "status", "result_hash", "decision"}
    assert "RAW_CHILD_RESULT_SHOULD_NOT_LEAK" not in repr(metadata)
    assert metadata["result_hash"]


def test_existing_l2_executor_still_contains_batch_memory_before_v0_freeze() -> None:
    source = inspect.getsource(executor.execute_l2)

    assert "batch_memory" in source
    assert "_parse_batch_memory" in source
