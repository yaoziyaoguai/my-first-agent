from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent.runtime.contracts import (
    ApprovalGrant,
    ApprovalRequired,
    ExecutionIntent,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.tools.file_ops import build_file_tool_runtime
from agent.tools.path_safety import WorkspaceBoundary, WorkspaceSecurityError


def _context() -> ToolPrepareContext:
    return ToolPrepareContext("conversation-1", "run-1", 1)


def _invoke(runtime, call: ToolCall):
    prepared = runtime.prepare(call, _context())
    assert isinstance(prepared, ExecutionIntent)
    return runtime.invoke(prepared)


def test_read_and_list_are_bounded_and_hide_sensitive_names(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "visible.txt").write_text("visible content", encoding="utf-8")
    (workspace / ".env").write_text("SECRET=fixture", encoding="utf-8")
    (workspace / "private.pem").write_text("fixture key", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)

    listed = _invoke(
        runtime,
        ToolCall("list-1", "list_files", {"path": "."}),
    )
    read = _invoke(
        runtime,
        ToolCall("read-1", "read_file", {"path": "visible.txt"}),
    )
    denied = runtime.prepare(
        ToolCall("read-2", "read_file", {"path": ".env"}),
        _context(),
    )

    assert "visible.txt" in listed.content
    assert ".env" not in listed.content
    assert "private.pem" not in listed.content
    assert read.content == "visible content"
    assert isinstance(denied, ToolResult)
    assert denied.is_error is True
    assert "SECRET" not in denied.content


def test_symlink_and_protected_hardlink_alias_are_denied(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside fixture", encoding="utf-8")
    protected = tmp_path / "state.json"
    protected.write_text("protected fixture", encoding="utf-8")
    protected.chmod(0o600)
    (workspace / "link.txt").symlink_to(outside)
    os.link(protected, workspace / "state-alias.json")
    runtime = build_file_tool_runtime(workspace, protected_paths=(protected,))

    symlink = runtime.prepare(
        ToolCall("read-1", "read_file", {"path": "link.txt"}),
        _context(),
    )
    hardlink = runtime.prepare(
        ToolCall("read-2", "read_file", {"path": "state-alias.json"}),
        _context(),
    )

    assert isinstance(symlink, ToolResult) and symlink.is_error
    assert isinstance(hardlink, ToolResult) and hardlink.is_error
    assert "outside fixture" not in symlink.content
    assert "protected fixture" not in hardlink.content


def test_unprotected_hardlink_alias_is_hidden_and_unreadable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-private.txt"
    outside.write_text("outside private fixture", encoding="utf-8")
    os.link(outside, workspace / "innocent.txt")
    runtime = build_file_tool_runtime(workspace)

    listed = _invoke(runtime, ToolCall("list-1", "list_files", {"path": "."}))
    denied = runtime.prepare(
        ToolCall("read-1", "read_file", {"path": "innocent.txt"}),
        _context(),
    )

    assert "innocent.txt" not in listed.content
    assert isinstance(denied, ToolResult) and denied.is_error
    assert "outside private fixture" not in denied.content


def test_default_private_roots_are_hidden_and_unreadable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private_names = ("config", "sessions", "runs", "memory", "skills", ".ua")
    for name in private_names:
        private = workspace / name
        private.mkdir()
        (private / "fixture.txt").write_text(f"private {name}", encoding="utf-8")
    (workspace / "agent_log.jsonl").write_text("private log", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)

    listed = _invoke(runtime, ToolCall("list-1", "list_files", {"path": "."}))

    for name in (*private_names, "agent_log.jsonl"):
        assert name not in listed.content
    denied = runtime.prepare(
        ToolCall("read-1", "read_file", {"path": "sessions/fixture.txt"}),
        _context(),
    )
    assert isinstance(denied, ToolResult) and denied.is_error
    assert "private sessions" not in denied.content


def test_file_resource_bounds_fail_closed_without_mutation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    oversized = workspace / "oversized.txt"
    oversized.write_text("0123456789", encoding="utf-8")
    target = workspace / "target.txt"
    target.write_text("small", encoding="utf-8")
    for name in ("a.txt", "b.txt", "c.txt"):
        (workspace / name).write_text("ok", encoding="utf-8")
    runtime = build_file_tool_runtime(
        workspace,
        max_file_bytes=8,
        max_list_entries=2,
    )

    read = _invoke(
        runtime,
        ToolCall("read-1", "read_file", {"path": "oversized.txt"}),
    )
    listed = _invoke(runtime, ToolCall("list-1", "list_files", {"path": "."}))
    write = runtime.prepare(
        ToolCall(
            "write-1",
            "write_file",
            {"path": "target.txt", "content": "0123456789"},
        ),
        _context(),
    )
    edit = runtime.prepare(
        ToolCall(
            "edit-1",
            "edit_file",
            {"path": "target.txt", "old_text": "small", "new_text": "0123456789"},
        ),
        _context(),
    )

    assert read.is_error and "0123456789" not in read.content
    assert listed.content.splitlines() == ["a.txt", "b.txt"]
    assert isinstance(write, ToolResult) and write.is_error
    assert isinstance(edit, ToolResult) and edit.is_error
    assert target.read_text(encoding="utf-8") == "small"


def test_control_characters_in_paths_fail_before_approval(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall(
            "write-1",
            "write_file",
            {"path": "note\n\x1b[2J.txt", "content": "fixture"},
        ),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert not (workspace / "note\n\x1b[2J.txt").exists()


def test_workspace_boundary_fails_closed_without_no_follow(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delattr(os, "O_NOFOLLOW")

    with pytest.raises(WorkspaceSecurityError, match="no-follow"):
        WorkspaceBoundary(tmp_path)


def test_write_requires_exact_approval_and_revalidates_precondition(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("before", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall(
        "write-1",
        "write_file",
        {"path": "note.txt", "content": "after"},
    )

    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    assert target.read_text(encoding="utf-8") == "before"

    target.write_text("changed by fixture", encoding="utf-8")
    stale = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
        ),
    )
    assert isinstance(stale, ToolResult)
    assert stale.metadata["code"] == "approval_mismatch"
    assert target.read_text(encoding="utf-8") == "changed by fixture"

    fresh_approval = runtime.prepare(call, _context())
    assert isinstance(fresh_approval, ApprovalRequired)
    intent = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            fresh_approval.request.request_id,
            fresh_approval.request.binding_digest,
        ),
    )
    assert isinstance(intent, ExecutionIntent)
    result = runtime.invoke(intent)

    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "after"


def test_edit_requires_unique_old_text_and_atomic_approved_write(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "note.txt"
    target.write_text("one two three", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall(
        "edit-1",
        "edit_file",
        {"path": "note.txt", "old_text": "two", "new_text": "TWO"},
    )

    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)
    intent = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
        ),
    )
    assert isinstance(intent, ExecutionIntent)

    result = runtime.invoke(intent)

    assert result.is_error is False
    assert target.read_text(encoding="utf-8") == "one TWO three"
