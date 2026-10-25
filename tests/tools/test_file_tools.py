from __future__ import annotations

import hashlib
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
from agent.runtime.tools import IntentConflictError
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


def test_explicit_project_paths_expose_only_the_selected_ordinary_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    config = workspace / "config"
    config.mkdir(parents=True)
    (config / "app.yaml").write_text("mode: fixture\n", encoding="utf-8")
    (config / "other.yaml").write_text("hidden fixture\n", encoding="utf-8")
    (config / ".env").write_text("SYNTHETIC=denied\n", encoding="utf-8")
    (workspace / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    runtime = build_file_tool_runtime(
        workspace,
        project_paths=("config/app.yaml", "pytest.ini"),
    )

    listed = _invoke(runtime, ToolCall("list-1", "list_files", {"path": "config"}))
    app = _invoke(
        runtime,
        ToolCall("read-1", "read_file", {"path": "config/app.yaml"}),
    )
    pytest_config = _invoke(
        runtime,
        ToolCall("read-2", "read_file", {"path": "pytest.ini"}),
    )
    denied_other = runtime.prepare(
        ToolCall("read-3", "read_file", {"path": "config/other.yaml"}),
        _context(),
    )
    denied_env = runtime.prepare(
        ToolCall("read-4", "read_file", {"path": "config/.env"}),
        _context(),
    )

    assert listed.content.splitlines() == ["app.yaml"]
    assert app.content == "mode: fixture\n"
    assert pytest_config.content == "[pytest]\n"
    assert isinstance(denied_other, ToolResult) and denied_other.is_error
    assert isinstance(denied_env, ToolResult) and denied_env.is_error


def test_project_path_exception_keeps_env_and_local_config_names_private(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    config = workspace / "config"
    config.mkdir(parents=True)
    (config / "app.yaml").write_text("mode: fixture\n", encoding="utf-8")
    private_names = (".envrc", ".env-production", "config.local")
    for name in private_names:
        (config / name).write_text("SYNTHETIC=private\n", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace, project_paths=("config",))

    visible = _invoke(
        runtime,
        ToolCall("read-visible", "read_file", {"path": "config/app.yaml"}),
    )
    listing = _invoke(
        runtime,
        ToolCall("list-config", "list_files", {"path": "config"}),
    )
    search = _invoke(
        runtime,
        ToolCall(
            "search-config",
            "search_text",
            {"query": "SYNTHETIC", "root": "config"},
        ),
    )
    denied = tuple(
        runtime.prepare(
            ToolCall(f"read-private-{index}", "read_file", {"path": f"config/{name}"}),
            _context(),
        )
        for index, name in enumerate(private_names)
    )
    denied_chunks = tuple(
        runtime.prepare(
            ToolCall(
                f"chunk-private-{index}",
                "read_file_chunk",
                {"path": f"config/{name}", "start_line": 1, "max_lines": 1},
            ),
            _context(),
        )
        for index, name in enumerate(private_names)
    )
    denied_writes = tuple(
        runtime.prepare(
            ToolCall(
                f"write-private-{index}",
                "write_file",
                {"path": f"config/{name}", "content": "replacement"},
            ),
            _context(),
        )
        for index, name in enumerate(private_names)
    )

    assert visible.content == "mode: fixture\n"
    assert listing.content.splitlines() == ["app.yaml"]
    assert "SYNTHETIC" not in search.content
    assert all(isinstance(result, ToolResult) and result.is_error for result in denied)
    assert all(
        isinstance(result, ToolResult) and result.is_error for result in denied_chunks
    )
    assert all(
        isinstance(result, ToolResult) and result.is_error for result in denied_writes
    )
    assert all("SYNTHETIC" not in result.content for result in denied)
    assert all(
        (config / name).read_text(encoding="utf-8") == "SYNTHETIC=private\n"
        for name in private_names
    )


def test_specific_project_file_grant_does_not_grant_an_ancestor_file(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "config").write_text("SYNTHETIC=ancestor\n", encoding="utf-8")
    runtime = build_file_tool_runtime(
        workspace,
        project_paths=("config/public.yaml",),
    )

    denied = runtime.prepare(
        ToolCall("read-ancestor", "read_file", {"path": "config"}),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert "SYNTHETIC" not in denied.content


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


def test_edit_content_conflict_points_to_reread_not_path_hygiene(
    tmp_path: Path,
) -> None:
    # r10（2026-10-24）：文件在模型上次读取后已变化时，old_text 不再精确匹配。
    # 这类失败必须按“内容冲突”给出重读指引，而不是路径卫生建议——
    # 否则模型在正确的路径上反复重试同一份过期 old_text。
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    log = workspace / "log.md"
    log.write_text("v2 content that already moved on\n", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall(
            "edit-stale",
            "edit_file",
            {
                "path": "log.md",
                "old_text": "v1 content the model last read",
                "new_text": "v1 content the model last read (edited)",
            },
        ),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert denied.metadata["code"] == "edit_content_conflict"
    assert "changed since" in denied.content
    assert "Re-read" in denied.content
    assert "current content" in denied.content
    assert "absolute" not in denied.content
    assert log.read_text(encoding="utf-8").startswith("v2 content")


def test_edit_path_hygiene_denial_keeps_path_guidance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall(
            "edit-abs",
            "edit_file",
            {"path": "/etc/passwd", "old_text": "x", "new_text": "y"},
        ),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert denied.metadata["code"] == "workspace_file_denied"
    assert "exact workspace-relative path" in denied.content


def test_write_to_missing_parent_explains_the_safe_next_step(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall(
            "write-missing-parent",
            "write_file",
            {"path": "reports/daily.md", "content": "fixture"},
        ),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert denied.metadata["code"] == "workspace_parent_missing"
    assert "parent directory does not exist" in denied.content
    assert "create it explicitly" in denied.content
    assert not (workspace / "reports").exists()


def test_make_directory_requires_exact_approval_then_creates_one_level(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall("mkdir-1", "make_directory", {"path": "reports"})

    approval = runtime.prepare(call, _context())

    assert isinstance(approval, ApprovalRequired)
    assert "create directory reports" in approval.request.preview
    assert not (workspace / "reports").exists()

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
    assert result.executed is True
    assert result.metadata["governed_tool_receipt_kind"] == "governed_tool_v1"
    assert (workspace / "reports").is_dir()
    assert (workspace / "reports").stat().st_mode & 0o777 == 0o700


def test_make_directory_never_creates_a_missing_parent_implicitly(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    denied = runtime.prepare(
        ToolCall("mkdir-1", "make_directory", {"path": "reports/2026"}),
        _context(),
    )

    assert isinstance(denied, ToolResult) and denied.is_error
    assert denied.metadata["code"] == "workspace_parent_missing"
    assert not (workspace / "reports").exists()


def test_make_directory_reports_an_existing_directory_without_a_fake_receipt(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "reports").mkdir(parents=True)
    runtime = build_file_tool_runtime(workspace)

    prepared = runtime.prepare(
        ToolCall("mkdir-1", "make_directory", {"path": "reports"}),
        _context(),
    )

    assert isinstance(prepared, ExecutionIntent)
    result = runtime.invoke(prepared)
    assert result.executed is False
    assert result.metadata["code"] == "directory_already_exists"
    assert "governed_tool_receipt_kind" not in result.metadata


def test_make_directory_rejects_an_approval_after_parent_identity_changes(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    parent = workspace / "reports"
    parent.mkdir(parents=True)
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall("mkdir-1", "make_directory", {"path": "reports/2026"})
    approval = runtime.prepare(call, _context())
    assert isinstance(approval, ApprovalRequired)

    parent.rename(workspace / "old-reports")
    parent.mkdir()
    stale = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
        ),
    )

    assert isinstance(stale, ToolResult) and stale.is_error
    assert stale.metadata["code"] == "approval_mismatch"
    assert not (parent / "2026").exists()


def test_nested_file_is_created_through_separate_directory_and_file_approvals(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)

    for call in (
        ToolCall("mkdir-1", "make_directory", {"path": "reports"}),
        ToolCall("mkdir-2", "make_directory", {"path": "reports/2026"}),
        ToolCall(
            "write-1",
            "write_file",
            {"path": "reports/2026/daily.md", "content": "# Daily\nApproved fixture.\n"},
        ),
    ):
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
        assert runtime.invoke(intent).is_error is False

    readback = _invoke(
        runtime,
        ToolCall("read-1", "read_file", {"path": "reports/2026/daily.md"}),
    )
    assert readback.content == "# Daily\nApproved fixture.\n"


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
    assert "before" not in approval.request.preview
    assert "after" in approval.request.preview
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


def test_confirm_file_shows_current_content_and_revalidates_before_readback(
    tmp_path: Path,
) -> None:
    """产物确认由 Runtime 展示当前内容；预览后的字节漂移必须 fail closed。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "report.txt"
    target.write_text("count=12\nerrors=3\n", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall("confirm-1", "confirm_file", {"path": "report.txt"})

    approval = runtime.prepare(call, _context())

    assert isinstance(approval, ApprovalRequired)
    assert "count=12" in approval.request.preview
    assert approval.request.new_content_digest is not None

    intent = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            approval.request.request_id,
            approval.request.binding_digest,
        ),
    )
    assert isinstance(intent, ExecutionIntent)
    target.write_text("count=12\nerrors=4\n", encoding="utf-8")

    with pytest.raises(IntentConflictError, match="preconditions changed"):
        runtime.invoke(intent)

    fresh = runtime.prepare(call, _context())
    assert isinstance(fresh, ApprovalRequired)
    fresh_intent = runtime.prepare(
        call,
        _context(),
        approval=ApprovalGrant(
            fresh.request.request_id,
            fresh.request.binding_digest,
        ),
    )
    assert isinstance(fresh_intent, ExecutionIntent)

    result = runtime.invoke(fresh_intent)

    assert result.is_error is False
    assert result.content == "count=12\nerrors=4\n"


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
    assert "two" in approval.request.preview
    assert "TWO" in approval.request.preview
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


def test_workspace_reads_mint_reusable_file_source_proofs(tmp_path: Path) -> None:
    """P5（2026-10-25 委托裁决）：读/列/搜的 Kernel 执行结果铸造 file-source
    proof（绑定 goal/revision/workspace/结果内容 digest），使其成为 r 许可
    （routine_workspace_read_v1）可覆盖的 reusable 来源。此前这些输出只能走
    reusable=False 的 generic 来源，读类任务逐次披露（E3 真实旅程 16-23 次
    决策的主驱动）。命令 stdout 等非 workspace 派生输出不在本铸造集合内。
    """

    workspace = tmp_path / "workspace"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "a.md").write_text("hello workspace", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    context = ToolPrepareContext(
        "conversation-1",
        "run-1",
        1,
        goal_id="goal-1",
        goal_revision=1,
        workspace_identity_digest="workspace-1",
    )
    cases = [
        ("read-1", "read_file", {"path": "notes/a.md"}, "notes/a.md"),
        ("list-1", "list_files", {"path": "notes"}, "notes"),
        ("sp-1", "search_paths", {"query": "a"}, "."),
        ("st-1", "search_text", {"query": "hello"}, "."),
        (
            "chunk-1",
            "read_file_chunk",
            {"path": "notes/a.md", "start_line": 1, "max_lines": 5},
            "notes/a.md",
        ),
    ]
    for call_id, name, arguments, target in cases:
        intent = runtime.prepare(ToolCall(call_id, name, arguments), context)
        assert isinstance(intent, ExecutionIntent)
        result = runtime.invoke(intent)
        assert result.is_error is False, (name, result.content)
        proof = result.result_source_proof
        assert proof is not None, f"{name} result must mint a file-source proof"
        assert proof.tool_name == name
        assert proof.normalized_target == target
        assert proof.goal_id == "goal-1"
        assert proof.goal_revision == 1
        assert proof.workspace_identity_digest == "workspace-1"
        assert proof.result_content_digest == hashlib.sha256(
            result.content.encode("utf-8")
        ).hexdigest()


def test_make_directory_result_does_not_mint_a_file_source_proof(
    tmp_path: Path,
) -> None:
    """目录创建是 workspace 效果但结果不是文件内容来源：不铸 proof，保持
    读域许可只覆盖"读到的内容"这一语义边界。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = build_file_tool_runtime(workspace)
    call = ToolCall("mkdir-1", "make_directory", {"path": "pkg"})
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
    result = runtime.invoke(intent)
    assert result.is_error is False
    assert result.result_source_proof is None


def test_read_proof_requires_goal_bound_context(tmp_path: Path) -> None:
    """无 goal/workspace 绑定的执行不铸 proof：降级为逐次披露，不伪造边界。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("content", encoding="utf-8")
    runtime = build_file_tool_runtime(workspace)
    result = _invoke(runtime, ToolCall("read-9", "read_file", {"path": "a.txt"}))
    assert result.is_error is False
    assert result.result_source_proof is None
