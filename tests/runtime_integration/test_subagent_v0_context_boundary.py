"""RED guardrails for Sub-agent v0 bounded context behavior."""

from __future__ import annotations

import json

import pytest

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
