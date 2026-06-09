"""RED guardrails for Sub-agent v0 bounded context behavior."""

from __future__ import annotations

import json

import pytest

from tests.runtime_integration.subagent_v0_contract_helpers import V0_XFAIL, route_v0


@pytest.mark.xfail(**V0_XFAIL)
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


@pytest.mark.xfail(**V0_XFAIL)
def test_no_uncontrolled_path_read_text_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path

    def forbidden_read_text(self: Path, *_args: object, **_kwargs: object) -> str:
        raise AssertionError(f"uncontrolled Path.read_text was called for {self}")

    monkeypatch.setattr(Path, "read_text", forbidden_read_text)

    result = route_v0(payload={
        "parent_context_blobs": {"a.py": "safe parent-provided content"},
        "child_requested_files": ("child-added.py",),
    })

    assert result.evidence["uncontrolled_path_read_text_calls"] == 0
    assert result.evidence["parent_policy_selects_all_files"] is True


@pytest.mark.xfail(**V0_XFAIL)
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


@pytest.mark.xfail(**V0_XFAIL)
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
