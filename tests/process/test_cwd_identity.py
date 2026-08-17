"""F3（P2 review finding 2026-08-16）：cwd 必须 bind descriptor identity（st_dev/st_ino）。

production 实测：同一路径目录 rm+mkdir 替换后，``cwd_digest``（path string sha256）
不变 → 旧 exact lease 仍匹配 → 批准的命令在新目录里执行。path string digest 不是
目录 identity；descriptor 必须进入 command fingerprint/candidate/lease，且 executor
在 invoke 紧邻 effect 时重验。workspace 外 symlink denial 不能替代同路径替换 Red。
"""

from __future__ import annotations

import os
import shutil
import stat

import pytest

from agent.composition import build_tool_registrations
from agent.process.tools import build_local_process_registration
from agent.runtime.contracts import (
    ApprovalRequired,
    ExecutionIntent,
    ProcessAuthorityLeaseV1,
    ToolCall,
    ToolPrepareContext,
    ToolResult,
)
from agent.runtime.tools import IntentConflictError, KernelToolRuntime


def _make_executable(workspace, marker) -> str:
    path = workspace / "marker-exe"
    path.write_bytes(f"#!/bin/sh\nprintf x >> {marker}\n".encode())
    os.chmod(path, stat.S_IRWXU)
    return str(path.relative_to(workspace))


def _goal_context(process_leases=()) -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-f3",
        run_id="run-f3",
        state_revision=1,
        goal_id="goal-f3",
        goal_revision=1,
        workspace_identity_digest="workspace-f3",
        process_leases=process_leases,
    )


def _lease_from_candidate(candidate) -> ProcessAuthorityLeaseV1:
    return ProcessAuthorityLeaseV1.create(
        lease_id=f"process-lease:{candidate.candidate_id}",
        candidate_digest=candidate.candidate_digest,
        goal_id=candidate.goal_id,
        goal_revision=candidate.goal_revision,
        workspace_identity_digest=candidate.workspace_identity_digest,
        command_fingerprint=candidate.command_fingerprint,
        readable_command=candidate.readable_command,
        executable_digest=candidate.executable_digest,
        argv_digest=candidate.argv_digest,
        cwd_digest=candidate.cwd_digest,
        resource_profile=candidate.resource_profile,
        environment_policy_digest=candidate.environment_policy_digest,
        execution_authority=candidate.execution_authority,
        approved_request_identity="req-f3",
        issued_at=candidate.issued_at,
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=0,
    )


def _setup(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    data = workspace / "data"
    data.mkdir()
    marker = str(tmp_path / "spawn-marker")
    runtime = KernelToolRuntime(
        (
            build_local_process_registration(
                workspace=workspace, captured_path="/usr/bin:/bin"
            ),
        )
    )
    rel = _make_executable(workspace, marker)
    arguments = {
        "executable": rel,
        "argv": [],
        "cwd": "data",
        "profile": "standard",
    }
    call = ToolCall("call-f3", "local_process", arguments)
    first = runtime.prepare(call, _goal_context())
    assert isinstance(first, ApprovalRequired)
    return runtime, call, first.request.process_authority_candidate, marker, data


def test_015_same_path_cwd_replacement_invalidates_exact_lease(tmp_path) -> None:
    """rm+mkdir 同路径替换后：旧 lease 不得匹配（descriptor 变了）→ 重新 approval。"""

    runtime, call, candidate, _marker, data = _setup(tmp_path)
    lease = _lease_from_candidate(candidate)
    same_path = runtime.prepare(
        call, _goal_context(process_leases=(lease,))
    )
    assert isinstance(same_path, ExecutionIntent), (
        "precondition: unchanged cwd directory still reuses the lease"
    )

    # 同路径替换：目录 identity（st_dev/st_ino）改变，path string 不变。
    shutil.rmtree(data)
    data.mkdir()

    replaced = runtime.prepare(call, _goal_context(process_leases=(lease,)))
    assert isinstance(replaced, ApprovalRequired), (
        "old exact lease must not match a replaced cwd directory (same path string)"
    )


def test_015_cwd_replacement_between_prepare_and_invoke_fails_closed(tmp_path) -> None:
    """prepare（lease 命中）后替换 cwd → invoke 不得在新目录里执行（零 spawn）。"""

    runtime, call, candidate, marker, data = _setup(tmp_path)
    lease = _lease_from_candidate(candidate)
    intent = runtime.prepare(call, _goal_context(process_leases=(lease,)))
    assert isinstance(intent, ExecutionIntent)

    shutil.rmtree(data)
    data.mkdir()

    with pytest.raises(IntentConflictError):
        runtime.invoke(intent)
    assert not os.path.exists(marker), "no spawn against the replaced directory"


def test_015_cwd_descriptor_is_bound_in_command_fingerprint(tmp_path) -> None:
    """descriptor 必须实际进入 fingerprint：两个同路径不同 inode 的 candidate
    fingerprint 必须不同（path string digest 相同也不行）。"""

    runtime, call, candidate, _marker, data = _setup(tmp_path)
    before = candidate.command_fingerprint

    shutil.rmtree(data)
    data.mkdir()

    second = runtime.prepare(call, _goal_context())
    assert isinstance(second, ApprovalRequired)
    after = second.request.process_authority_candidate.command_fingerprint
    assert before != after, "command fingerprint must bind cwd descriptor identity"


def test_015_missing_cwd_rejected_before_approval(tmp_path) -> None:
    """prepare 时 cwd 不存在 → binding_failure（approval 前拒绝，不展示幻想 cwd）。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime(
        (
            build_local_process_registration(
                workspace=workspace, captured_path="/usr/bin:/bin"
            ),
        )
    )
    rel = _make_executable(workspace, str(tmp_path / "m"))
    result = runtime.prepare(
        ToolCall(
            "call-f3b",
            "local_process",
            {"executable": rel, "argv": [], "cwd": "missing", "profile": "standard"},
        ),
        _goal_context(),
    )
    assert isinstance(result, ToolResult)
    assert result.is_error is True
    assert result.metadata.get("code") == "binding_failure"


@pytest.mark.parametrize("cwd_kind", ["private", "symlink"])
def test_015_cwd_reuses_workspace_boundary_denials(tmp_path, cwd_kind) -> None:
    """R13 / design §7.1：process cwd 必须复用统一 no-follow/private boundary。

    只做 ``Path.resolve()+containment`` 会接受 private root 和 workspace 内 symlink，
    与文件工具的安全边界分裂；两类都必须在 approval 前 ``binding_failure``。
    """

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    private = workspace / "private"
    private.mkdir()
    real = workspace / "real"
    real.mkdir()
    link = workspace / "link"
    link.symlink_to(real, target_is_directory=True)
    marker = str(tmp_path / "boundary-marker")
    rel = _make_executable(workspace, marker)
    registrations = build_tool_registrations(
        workspace=workspace,
        private_roots=("private",),
        max_tool_result_chars=64_000,
        captured_path="/usr/bin:/bin",
    )
    runtime = KernelToolRuntime(registrations)
    cwd = "private" if cwd_kind == "private" else "link"
    result = runtime.prepare(
        ToolCall(
            f"call-boundary-{cwd_kind}",
            "local_process",
            {"executable": rel, "argv": [], "cwd": cwd, "profile": "standard"},
        ),
        _goal_context(),
    )
    assert isinstance(result, ToolResult)
    assert result.executed is False
    assert result.metadata.get("code") == "binding_failure"
    assert not os.path.exists(marker)
