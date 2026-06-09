"""RED guardrails for Sub-agent v0 bounded context behavior."""

from __future__ import annotations

import json

import pytest


@pytest.mark.xfail(strict=True, reason="Sub-agent v0 bounded context builder not implemented yet")
def test_context_uses_parent_selected_files_and_enforces_limits() -> None:
    from agent.runtime_integration import subagent_action

    context = subagent_action.build_subagent_v0_context(
        parent_selected_files=("a.py", "b.py"),
        child_requested_files=("c.py",),
        max_context_chars=20,
        max_files=1,
    )

    assert context.context_file_count == 1
    assert context.context_length <= 20
    assert context.files == ("a.py",)
    assert "c.py" not in context.files


@pytest.mark.xfail(strict=True, reason="V0 context builder still missing Path.read_text guard")
def test_no_uncontrolled_path_read_text_expansion() -> None:
    from agent.runtime_integration import subagent_action

    audit = subagent_action.audit_subagent_v0_context_builder()

    assert audit.uncontrolled_path_read_text_calls == 0
    assert audit.parent_policy_selects_all_files is True


@pytest.mark.xfail(strict=True, reason="V0 context evidence redaction not implemented yet")
def test_context_evidence_contains_only_hash_length_count_and_no_raw_path_or_text() -> None:
    from agent.runtime_integration import subagent_action

    event = subagent_action.subagent_v0_context_built_event(
        raw_context_text="RAW_CONTEXT_SHOULD_NOT_LEAK",
        raw_path="/tmp/RAW_PATH_SHOULD_NOT_LEAK.py",
    )
    metadata = event.metadata
    serialized = json.dumps(metadata, default=str)

    assert {"context_hash", "context_length", "context_file_count"} <= set(metadata)
    assert "RAW_CONTEXT_SHOULD_NOT_LEAK" not in serialized
    assert "RAW_PATH_SHOULD_NOT_LEAK" not in serialized
    assert "raw_context" not in metadata
    assert "path" not in metadata


@pytest.mark.xfail(strict=True, reason="V0 parent context mutation guard not implemented yet")
def test_child_cannot_add_files_or_mutate_parent_context_prompt_or_messages() -> None:
    from agent.runtime_integration import subagent_action

    parent_state = {
        "context_files": ("parent.py",),
        "context": {"safe": True},
        "prompt": "parent prompt",
        "messages": (),
    }
    before = repr(parent_state)

    result = subagent_action.apply_subagent_v0_child_context_intent(
        parent_state,
        child_requested_files=("child-added.py",),
        child_prompt_patch="RAW_PROMPT_PATCH",
        child_message={"role": "assistant", "content": "RAW_CHILD_OUTPUT"},
    )

    assert result.status in {"failed", "policy_blocked"}
    assert repr(parent_state) == before
