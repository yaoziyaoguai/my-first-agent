"""任务切换（Oracle gap2 #1，2026-10-26）：park→new→switch→select→resume。

契约分三层钉住：
- gate（agent/cli/actions.py）：/new 放宽到 PAUSED Goal（持久安全边界，leases 已
  撤销），活跃 Goal 拒绝并给 /pause 指引；/switch 只要求无 active run，Goal 任意
  状态允许（切换不执行、不转移任何 pending 决策与授权）；
- REPL（agent/cli/app.py）：/switch 以 SWITCH_SESSION_REQUESTED(78) 交还装配层，
  与 /new(79) 同一进程内信令；
- 装配循环（main.py + sessions.select_required）：/switch 关掉当前 conversation
  资源后强制重开会话选择器（单个非终态候选也不自动 resume）。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import main as entrypoint
from agent.cli.actions import (
    NEW_SESSION_REQUESTED,
    SWITCH_SESSION_REQUESTED,
    new_session_gate,
    switch_session_gate,
)
from agent.cli.app import run_repl
from agent.continuity.sessions import StartupDisposition, open_workspace_session
from agent.runtime.contracts import (
    ActiveRun,
    ActiveRunStatus,
    ApprovalRequest,
    ContinuationPhase,
    ConversationState,
    GoalStatus,
    LoadedSnapshot,
    ToolCall,
)
from tests.kernel.fakes import (
    conversation_with_active_goal,
    conversation_with_terminal_goal,
)


class StaticStore:
    def __init__(self, state: ConversationState) -> None:
        self.state = state

    def load(self) -> LoadedSnapshot:
        return LoadedSnapshot(self.state, "token-1")


def _paused_state() -> ConversationState:
    active = conversation_with_active_goal()
    return replace(active, goal=replace(active.goal, status=GoalStatus.PAUSED))


def _pending_approval_state() -> ConversationState:
    goal = conversation_with_active_goal().goal
    return replace(
        ConversationState.new("conversation-pending"),
        goal=goal,
        active_run=ActiveRun(
            "run-1",
            status=ActiveRunStatus.AWAITING_APPROVAL,
            phase=ContinuationPhase.TOOL,
            pending_request=ApprovalRequest(
                request_id="approval-1",
                run_id="run-1",
                tool_call_id="call-1",
                binding_digest="binding-1",
                preview="write note.txt (5 bytes)",
            ),
            tool_calls=(ToolCall("call-1", "write_file", {}),),
        ),
    )


# ---- gate 单元（与 TUI 共享同一语义） ----


def test_new_session_gate_allows_paused_goal_without_active_run() -> None:
    # park 语义：/pause 已在持久安全边界收尾 run 并撤销 leases，/new 允许离开。
    assert new_session_gate(_paused_state()) is None


def test_new_session_gate_still_rejects_active_goal_with_pause_hint() -> None:
    refusal = new_session_gate(conversation_with_active_goal())
    assert refusal is not None
    assert "/pause" in refusal


def test_new_session_gate_rejects_paused_goal_with_pending_run() -> None:
    paused = _pending_approval_state()
    paused = replace(
        paused, goal=replace(paused.goal, status=GoalStatus.PAUSED)
    )
    refusal = new_session_gate(paused)
    assert refusal is not None
    assert "pending run" in refusal


def test_switch_session_gate_requires_no_active_run() -> None:
    refusal = switch_session_gate(_pending_approval_state())
    assert refusal is not None
    assert "switching" in refusal


def test_switch_session_gate_allows_any_goal_status() -> None:
    # 切换不清空、不重开 Goal：活跃、暂停、终态、无 Goal 都允许，
    # conversation 原样保留为 startup 候选。
    assert switch_session_gate(conversation_with_active_goal()) is None
    assert switch_session_gate(_paused_state()) is None
    assert (
        switch_session_gate(
            conversation_with_terminal_goal(GoalStatus.VERIFIED_DONE)
        )
        is None
    )
    assert switch_session_gate(ConversationState.new("conversation-goalless")) is None


# ---- REPL 命令 ----


def test_repl_switch_returns_session_requested_code() -> None:
    writes: list[str] = []
    code = run_repl(
        None,
        StaticStore(_paused_state()),
        input_fn=lambda _prompt: "/switch",
        write_fn=writes.append,
    )
    assert code == SWITCH_SESSION_REQUESTED == 78
    assert any("Switching to another saved conversation" in line for line in writes)


def test_repl_switch_refusal_keeps_repl_alive() -> None:
    writes: list[str] = []
    inputs = iter(("/switch", "/exit"))
    code = run_repl(
        None,
        StaticStore(_pending_approval_state()),
        input_fn=lambda _prompt: next(inputs),
        write_fn=writes.append,
    )
    assert code == 0
    assert any("Resolve the pending run" in line for line in writes)


def test_repl_new_allows_paused_goal() -> None:
    writes: list[str] = []
    code = run_repl(
        None,
        StaticStore(_paused_state()),
        input_fn=lambda _prompt: "/new",
        write_fn=writes.append,
    )
    assert code == NEW_SESSION_REQUESTED == 79
    assert any("Starting a new task" in line for line in writes)


def test_repl_help_lists_switch() -> None:
    writes: list[str] = []
    inputs = iter(("/help", "/exit"))
    code = run_repl(
        None,
        StaticStore(ConversationState.new("conversation-help")),
        input_fn=lambda _prompt: next(inputs),
        write_fn=writes.append,
    )
    assert code == 0
    assert any("/switch" in line for line in writes)


# ---- 装配循环：/switch 重开会话选择器 ----


def test_main_switch_forces_selector_reentry_over_saved_conversations(
    tmp_path: Path, monkeypatch
) -> None:
    """两个已保存 conversation：startup 选择 1 个 → REPL /switch → 选择器再次
    出现（不自动 resume）→ 选另一个 → 正常退出；两个 checkpoint 原样保留。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"

    first = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000031",
    )
    assert first.disposition is StartupDisposition.CREATED
    second = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000032",
        force_new=True,
    )
    assert second.disposition is StartupDisposition.CREATED

    repl_codes = iter((SWITCH_SESSION_REQUESTED, 0))
    monkeypatch.setattr(
        entrypoint, "run_repl", lambda *args, **kwargs: next(repl_codes)
    )
    # 第一次：startup SELECT_REQUIRED 选 1；第二次：/switch 后 select_required
    # 再选 2。两个候选都是无 Goal 会话（非终态），顺序按加载序稳定。
    inputs = iter(("1", "2"))
    output: list[str] = []
    code = entrypoint.main(
        [
            "--workspace", str(workspace),
            "--state-root", str(state_root),
            "--provider", "fake",
        ],
        input_fn=lambda _prompt: next(inputs),
        write_fn=output.append,
    )

    assert code == 0, output
    selector_count = sum(
        line.startswith("Several saved conversations or unfinished tasks")
        for line in output
    )
    assert selector_count == 2, output
    # 两个 conversation checkpoint 都原样保留在磁盘上（切换不清除历史）。
    assert first.checkpoint_path is not None and first.checkpoint_path.exists()
    assert second.checkpoint_path is not None and second.checkpoint_path.exists()


def test_main_switch_to_single_candidate_does_not_auto_resume(
    tmp_path: Path, monkeypatch
) -> None:
    """唯一候选（当前 conversation 自身）也走 SELECT_REQUIRED，不静默 resume。"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state-root"
    only = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-000000000041",
    )
    assert only.disposition is StartupDisposition.CREATED

    repl_codes = iter((SWITCH_SESSION_REQUESTED, 0))
    monkeypatch.setattr(
        entrypoint, "run_repl", lambda *args, **kwargs: next(repl_codes)
    )
    inputs = iter(("1",))
    output: list[str] = []
    code = entrypoint.main(
        [
            "--workspace", str(workspace),
            "--state-root", str(state_root),
            "--provider", "fake",
        ],
        input_fn=lambda _prompt: next(inputs),
        write_fn=output.append,
    )

    assert code == 0, output
    # startup 单候选自动 RESUMED（无选择器）；/switch 后强制出现选择器一次。
    selector_count = sum(
        line.startswith("Several saved conversations or unfinished tasks")
        for line in output
    )
    assert selector_count == 1, output
