"""015 U8：process authority 的 CLI/TUI/headless parity。

approval preview 携带 exact command + same-UID notice + closed profile（所有 adapter 读同一
ApprovalRequest.preview 字符串）；``project_process_leases`` 默认隐藏 digest、advanced 暴露；
RevokeProcessAuthority 是单一 typed RuntimeAction，各 adapter 翻译为同一 reducer 入口。
"""

from __future__ import annotations

import os
import stat
from dataclasses import replace
from pathlib import Path

from agent.process.tools import build_local_process_registration
from agent.runtime.contracts import (
    ConversationState,
    ExecutionAuthorityClass,
    GoalFrame,
    GoalStatus,
    ProcessAuthorityLeaseV1,
    ProposedCriterion,
    RevokeProcessAuthority,
    ToolCall,
    ToolPrepareContext,
)
from agent.runtime.state import accept_action, pause_for_approval, start_tool_batch
from agent.runtime.tools import KernelToolRuntime
from agent.runtime.views import project_process_leases


def _goal_context() -> ToolPrepareContext:
    return ToolPrepareContext(
        conversation_id="conversation-u8",
        run_id="run-u8",
        state_revision=1,
        goal_id="goal-u8",
        goal_revision=1,
        workspace_identity_digest="workspace-u8",
    )


def _make_executable(workspace: Path) -> str:
    path = workspace / "fixture-exe"
    path.write_bytes(b"#!/bin/sh\necho hi\n")
    os.chmod(path, stat.S_IRWXU)
    return str(path.relative_to(workspace))


def test_015_approval_preview_carries_exact_command_same_uid_notice_and_profile(
    tmp_path: Path,
) -> None:
    """R7/AE1：approval preview 含 exact argv + same-UID + profile（各 adapter 共享）。"""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = KernelToolRuntime(
        (build_local_process_registration(workspace=workspace, captured_path="/usr/bin:/bin"),)
    )
    rel = _make_executable(workspace)
    from agent.runtime.contracts import ApprovalRequired

    result = runtime.prepare(
        ToolCall(
            "call-u8",
            "local_process",
            {"executable": rel, "argv": ["--exact", "a;b"], "cwd": ".", "profile": "standard"},
        ),
        _goal_context(),
    )
    assert isinstance(result, ApprovalRequired)
    preview = result.request.preview
    lowered = preview.casefold()
    assert "same-uid" in lowered
    assert "--exact" in preview  # exact argv literal
    assert "a;b" in preview  # metacharacter 作为 literal 出现在 preview
    assert "standard" in preview  # closed profile
    assert result.request.process_authority_candidate is not None
    candidate = result.request.process_authority_candidate
    assert candidate.execution_authority is ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS


def test_015_project_process_leases_default_hides_digest_advanced_exposes(tmp_path: Path) -> None:
    """R11/§12.2：lease projection 默认隐藏 digest、advanced 暴露；各 adapter 共享。"""

    lease = ProcessAuthorityLeaseV1.create(
        lease_id="process-lease:candidate-x",
        candidate_digest="c" * 64,
        goal_id="goal-u8",
        goal_revision=1,
        workspace_identity_digest="workspace-u8",
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --visible",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        approved_request_identity="req-u8",
        issued_at="2026-08-09T00:00:00Z",
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=2,
    )
    goal = GoalFrame(
        goal_id="goal-u8",
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest="workspace-u8",
        user_outcome="governed local action",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-u8", "command contract"),),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-09T00:00:00Z",
        updated_at="2026-08-09T00:00:00Z",
    )
    state = replace(
        ConversationState.new("conversation-u8"), goal=goal, process_leases=(lease,)
    )

    default = project_process_leases(state)
    advanced = project_process_leases(state, advanced=True)
    assert len(default) == 1 == len(advanced)
    assert default[0].remaining_uses == 6  # 8 - 2 consumed
    assert default[0].resource_profile == "standard"
    assert default[0].expires_at == "2099-12-31T23:59:59Z"
    assert default[0].lease_digest is None  # 默认隐藏
    assert advanced[0].lease_digest == lease.lease_digest  # advanced 暴露


def test_015_revoke_typed_action_is_single_reducer_entry_for_all_adapters() -> None:
    """R11/§8：CLI/TUI/headless 翻译为同一 RevokeProcessAuthority typed action。"""

    revoke_single = RevokeProcessAuthority(
        conversation_id="conversation-u8",
        action_seq=2,
        expected_revision=1,
        lease_id="process-lease:candidate-x",
    )
    revoke_all = RevokeProcessAuthority(
        conversation_id="conversation-u8",
        action_seq=3,
        expected_revision=2,
        lease_id=None,
    )
    # 同一 typed action 类型；lease_id 区分 single vs all；expected_revision 提供 CAS。
    assert isinstance(revoke_single, RevokeProcessAuthority)
    assert revoke_single.lease_id == "process-lease:candidate-x"
    assert revoke_all.lease_id is None
    assert revoke_single.expected_revision == 1


def _lease_state() -> ConversationState:
    """F5：带一条 active lease 的 authoritative state（复用本文件合同形状）。"""

    lease = ProcessAuthorityLeaseV1.create(
        lease_id="process-lease:candidate-x",
        candidate_digest="c" * 64,
        goal_id="goal-u8",
        goal_revision=1,
        workspace_identity_digest="workspace-u8",
        command_fingerprint="f" * 64,
        readable_command="/usr/bin/true --visible",
        executable_digest="e" * 64,
        argv_digest="a" * 64,
        cwd_digest="w" * 64,
        resource_profile="standard",
        environment_policy_digest="p" * 64,
        execution_authority=ExecutionAuthorityClass.LOCAL_SAME_UID_PROCESS,
        approved_request_identity="req-u8",
        issued_at="2026-08-09T00:00:00Z",
        expires_at="2099-12-31T23:59:59Z",
        max_uses=8,
        uses_consumed=2,
    )
    goal = GoalFrame(
        goal_id="goal-u8",
        revision=1,
        created_from_fact_ids=("fact-user",),
        workspace_identity_digest="workspace-u8",
        user_outcome="governed local action",
        beneficiary="user",
        targets=("artifact.txt",),
        scope=("workspace",),
        non_goals=(),
        assumptions=(),
        proposed_criteria=(ProposedCriterion("criterion-u8", "command contract"),),
        admitted_criteria=(),
        authority_snapshot="fixed-composition",
        status=GoalStatus.GOAL_READY,
        created_at="2026-08-09T00:00:00Z",
        updated_at="2026-08-09T00:00:00Z",
    )
    return replace(
        ConversationState.new("conversation-u8"), goal=goal, process_leases=(lease,)
    )


def test_015_cli_adapters_translate_revoke_to_typed_action() -> None:
    """F5（P2 review finding / R11）：CLI `/revoke` 必须经 adapter 真实翻译为
    RevokeProcessAuthority（CAS expected_revision），不是只测直接构造 typed action。"""

    from agent.cli.app import _parse_action

    state = _lease_state()
    make_run_id = lambda: "run-u8"  # noqa: E731

    action, error = _parse_action(
        "/revoke process-lease:candidate-x", state, make_run_id
    )
    assert error is None
    assert isinstance(action, RevokeProcessAuthority)
    assert action.lease_id == "process-lease:candidate-x"
    assert action.expected_revision == state.revision  # reload/CAS
    assert action.conversation_id == state.conversation_id
    assert action.action_seq == state.next_action_seq

    all_action, all_error = _parse_action("/revoke all", state, make_run_id)
    assert all_error is None
    assert isinstance(all_action, RevokeProcessAuthority)
    assert all_action.lease_id is None  # 全部撤销

    unknown_action, unknown_error = _parse_action("/revoke nope", state, make_run_id)
    assert unknown_action is None
    assert unknown_error is not None  # 未知 lease id 必须有 typed 反馈，不静默

    empty_state = replace(ConversationState.new("conversation-u8"), process_leases=())
    empty_action, empty_error = _parse_action(
        "/revoke all", empty_state, make_run_id
    )
    assert empty_action is None
    assert empty_error is not None


def test_015_cli_approval_records_injected_approval_time() -> None:
    """CLI 的真实 yes 路径把批准发生时刻写入 typed action。"""

    from agent.cli.app import _parse_action
    from agent.runtime.contracts import ApprovalRequest, ResolveApproval, SubmitMessage

    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="conversation-u8",
            action_seq=1,
            expected_revision=0,
            run_id="run-u8",
            message="approve",
        ),
    ).state
    batched = start_tool_batch(started, (ToolCall("call-u8", "write_file", {}),))
    paused = pause_for_approval(
        batched,
        ApprovalRequest(
            request_id="approval-u8",
            run_id="run-u8",
            tool_call_id="call-u8",
            binding_digest="binding-u8",
            preview="write",
        ),
    )
    approved_at = "2026-08-16T12:00:00Z"
    action, error = _parse_action(
        "yes",
        paused,
        lambda: "unused-run",
        approval_time_factory=lambda: approved_at,
    )
    assert error is None
    assert isinstance(action, ResolveApproval)
    assert action.approved_at == approved_at


def test_015_cli_repl_and_renderer_surface_leases() -> None:
    """F5/R11：`/leases` 在 REPL 渲染 readable 摘要（默认隐藏 digest；--advanced 暴露）。"""

    from agent.cli.app import run_repl
    from agent.cli.render import TerminalRenderer

    state = _lease_state()

    class _FakeStore:  # /leases 与 /exit 不触达 runtime；store 仅 load() 投影。
        def load(self):  # noqa: ANN202
            import types

            return types.SimpleNamespace(state=state)

    def _run_commands(commands: list[str]) -> list[str]:
        outputs: list[str] = []
        inputs = iter([*commands, "/exit"])
        run_repl(
            None,  # noqa: ARG005 - typed command path 不调用 runtime
            _FakeStore(),
            input_fn=lambda _prompt: next(inputs),
            write_fn=outputs.append,
            renderer=TerminalRenderer(outputs.append),
        )
        return outputs

    default_block = "".join(_run_commands(["/leases"]))
    advanced_block = "".join(_run_commands(["/leases --advanced"]))
    assert "standard" in default_block
    assert "2099-12-31T23:59:59Z" in default_block  # expires 可读
    digest = state.process_leases[0].lease_digest
    assert digest not in default_block  # 默认隐藏 lease digest
    assert digest in advanced_block  # --advanced 暴露 digest
    assert "process-lease:candidate-x" in advanced_block  # 撤销所需精确 id


def test_015_tui_and_headless_surface_leases() -> None:
    """F5/R11：TUI 命令翻译 + headless 只读投影共用同一 lease view/typed action。"""

    state = _lease_state()

    from agent.cli.app import load_headless_leases
    from agent.tui.app import parse_process_command

    class _FakeStore:
        def load(self):  # noqa: ANN202
            import types

            return types.SimpleNamespace(state=state)

    leases = load_headless_leases(_FakeStore())
    assert len(leases) == 1
    assert leases[0].resource_profile == "standard"
    assert leases[0].lease_digest is None
    advanced = load_headless_leases(_FakeStore(), advanced=True)
    assert advanced[0].lease_digest == state.process_leases[0].lease_digest

    kind, payload = parse_process_command(
        "/revoke process-lease:candidate-x", state
    )
    assert kind == "action"
    assert isinstance(payload, RevokeProcessAuthority)
    assert payload.lease_id == "process-lease:candidate-x"

    view_kind, views = parse_process_command("/leases", state)
    assert view_kind == "leases"
    assert views[0].remaining_uses == 6

    assert parse_process_command("hello", state) is None  # 普通消息不是命令
