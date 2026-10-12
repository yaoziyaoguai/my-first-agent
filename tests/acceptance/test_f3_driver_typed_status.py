"""F3a：完成判定只认 typed 终态，文字与业务文件正确性不能自证完成。"""

from __future__ import annotations

from pathlib import Path

from agent.runtime.contracts import GoalStatus
from scripts.run_real_coding_scenario import (
    DogfoodOperator,
    _load_final_state,
    _typed_completion,
    product_ran_related_tests,
)
from tests.acceptance import f3_helpers


def _write_checkpoint(tmp_path: Path, status: GoalStatus):
    """R2a：经真实 open_workspace_session 建立 workspaces/<scope> 布局。"""

    from agent.continuity.sessions import open_workspace_session

    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    state_root = tmp_path / "state"
    opened = open_workspace_session(
        workspace,
        state_root=state_root,
        conversation_id_factory=lambda: "00000000-0000-4000-8000-0000000003f3",
    )
    f3_helpers.checkpoint(
        opened.checkpoint_path,
        status=status,
    )
    return workspace, state_root


def test_f3_model_text_task_is_closed_is_not_completion(tmp_path: Path) -> None:
    """A09-1：模型文本含 Task is closed. 且真实 Goal 活跃 → 不得签完成。"""

    workspace, state_root = _write_checkpoint(tmp_path, GoalStatus.GOAL_READY)
    state = _load_final_state(workspace, state_root)
    operator = DogfoodOperator(task="fix", max_consents=2, max_resumes=0)
    # 文字提示仍只是 UI 辅助：operator 不会再把该文案读成完成信号。
    assert operator.next_input(("First Agent is ready",)) == "fix"
    assert operator.next_input(("Task is closed.",)) == "/exit"
    assert operator.stop_reason == "unexpected_idle_before_verified_done"
    # typed 判定：GOAL_READY 不是完成。
    assert _typed_completion(state) is False
    ok, reason = product_ran_related_tests(state)
    assert ok is False and reason


def test_f3_cancelled_goal_with_correct_files_is_not_autonomous_completion(
    tmp_path: Path,
) -> None:
    """A09-2：真实 CANCELLED + 最终文件恰巧正确 → 不得作为自主完成。"""

    workspace, state_root = _write_checkpoint(tmp_path, GoalStatus.CANCELLED)
    state = _load_final_state(workspace, state_root)
    assert _typed_completion(state) is False
    ok, reason = product_ran_related_tests(state)
    assert ok is False and reason
