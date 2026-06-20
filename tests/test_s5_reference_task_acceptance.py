"""S5-G05 fake/local recovery E2E（参考任务级 acceptance）。

镜像 S2/S4 参考任务测试的 harness，叠加 S5 durable ledger：一个确定性的 fake/local
governed task在 step 0 完成并写入 checkpoint+ledger 后「中断」，从 checkpoint+ledger
重载、通过一致性检查、经 governed runtime 路径继续 step 1 直到完成。证明：

- AC-4：checkpoint 仍是状态恢复源，ledger 提供 durable 连续性，两者不静默分歧；
- AC-5：恢复后从 step 1 继续，step 0 不被静默重复；恢复走 governed runtime 路径；
- AC-7：合成 key 经 record_checkpoint_boundary→ledger 落盘时被 redact。

本测试组合 G01-G04 已验证单元，是参考任务级 acceptance（与 S2/S4 同模式）。
"""

from __future__ import annotations

from agent.checkpoint import (
    clear_checkpoint,
    load_checkpoint_to_state,
    save_checkpoint,
)
from agent.state import create_agent_state
from agent.task_ledger import StepProgressRecord, assert_monotonic_order
from agent.task_ledger_cooperation import (
    check_recovery_consistency,
    latest_checkpoint_ref,
    record_checkpoint_boundary,
)
from agent.task_ledger_store import TaskLedger
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
)
from agent.task_state_model import GovernedTaskLifecycle, build_governed_task_state
from config import STEP_COMPLETION_THRESHOLD

_SECRET = "sk-leaksurvives123456"


def _s5_recovery_plan() -> dict:
    return {
        "goal": "s5 durable recovery demo",
        "thinking": "two steps; interrupt after step 0; resume and finish step 1",
        "steps": [
            {
                "step_id": "s5-recovery-1",
                "title": "Inspect baseline",
                "description": "Read S5 baseline + ledger contract.",
                "step_type": "read",
            },
            {
                "step_id": "s5-recovery-2",
                "title": "Apply focused change",
                "description": "Apply a local change and verify.",
                "step_type": "edit",
            },
        ],
    }


def _record_tool_result(state, *, tool_use_id: str, tool_name: str, result: str) -> None:
    state.task.tool_execution_log[tool_use_id] = {
        "tool": tool_name,
        "status": "executed",
        "input": {"target": "s5 reference task fixture"},
        "result": result,
        "step_index": state.task.current_step_index,
    }


def _mark_step_complete(state, *, tool_use_id: str, summary: str) -> None:
    state.task.tool_execution_log[tool_use_id] = {
        "tool": "mark_step_complete",
        "status": "meta_recorded",
        "input": {
            "completion_score": STEP_COMPLETION_THRESHOLD,
            "summary": summary,
            "outstanding": "none",
        },
        "step_index": state.task.current_step_index,
    }


def test_s5_reference_task_fake_recovery_e2e(tmp_path):
    checkpoint_path = tmp_path / "s5-recovery-checkpoint.json"
    ledger_path = tmp_path / "s5-recovery-ledger.jsonl"
    task_id = "s5-recovery-task"
    ledger = TaskLedger(ledger_path)

    # --- Phase 1: 把 step 0 跑到完成，记录 durable 边界，然后「中断」 ---
    state = create_agent_state(system_prompt="S5 recovery test runtime")
    state.memory.session_id = "s5-recovery-session"
    state.memory.working_summary = "Prior S5 loop context is available."

    receive_governed_task(
        state,
        user_goal="S5 durable recovery demo",
        plan_payload=_s5_recovery_plan(),
    )
    assert accept_governed_plan(state).allowed is True

    _record_tool_result(
        state, tool_use_id="tool-read-0", tool_name="read_file", result="inspected baseline"
    )
    _mark_step_complete(
        state, tool_use_id="meta-0", summary=f"step 0 done; token={_SECRET}"
    )
    # 在 step 0 仍是 current step 且已 completed 时记录边界 → ledger 捕获 step 0 完成。
    save_checkpoint(state, source="s5.step0", path=checkpoint_path)
    record_checkpoint_boundary(
        ledger,
        build_governed_task_state(state),
        task_id=task_id,
        checkpoint_ref=str(checkpoint_path),
        checkpoint_source="step0_complete",
        recorded_at="t1",
    )
    # 推进到 step 1，持久化，记录恢复点边界。
    advance_governed_task_if_ready(state)
    save_checkpoint(state, source="s5.step0-advanced", path=checkpoint_path)
    record_checkpoint_boundary(
        ledger,
        build_governed_task_state(state),
        task_id=task_id,
        checkpoint_ref=str(checkpoint_path),
        checkpoint_source="step1_active",
        recorded_at="t2",
    )
    # INTERRUPT：进程内丢弃 state；durable 状态 = checkpoint 文件 + ledger 文件。
    del state

    # 集成 AC-7：raw ledger 文件不得携带合成 secret（record_checkpoint_boundary→append 已 redact）。
    assert _SECRET not in ledger_path.read_text(encoding="utf-8")

    # --- Phase 2：从 checkpoint+ledger 重载，校验一致性，经 governed 路径继续 ---
    resumed = create_agent_state(system_prompt="S5 recovery test runtime")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path) is True
    resumed_governed = build_governed_task_state(resumed)
    # 恢复在 step 1 —— step 0 未被重复。
    assert resumed_governed.progress.current_step_index == 1
    assert resumed_governed.progress.completed_steps == 1

    reopened = TaskLedger(ledger_path)
    report = check_recovery_consistency(
        reopened.read_all(),
        checkpoint_ref_exists=checkpoint_path.exists(),
        governed_state=resumed_governed,
    )
    assert report.ok, [issue.kind for issue in report.issues]

    # 经 governed runtime 路径继续 step 1。
    _record_tool_result(
        resumed, tool_use_id="tool-edit-1", tool_name="apply_patch", result="applied change"
    )
    _mark_step_complete(resumed, tool_use_id="meta-1", summary="step 1 done")
    record_checkpoint_boundary(
        reopened,
        build_governed_task_state(resumed),
        task_id=task_id,
        checkpoint_ref=str(checkpoint_path),
        checkpoint_source="step1_complete",
        recorded_at="t3",
    )
    completed = advance_governed_task_if_ready(resumed)
    assert completed.snapshot.lifecycle is GovernedTaskLifecycle.DONE
    assert completed.snapshot.progress.percent == 100.0

    # --- 一条连贯的 governed task 历史 ---
    records = reopened.read_all()
    completed_indices = sorted(
        {
            record.step_index
            for record in records
            if isinstance(record, StepProgressRecord) and record.step_status == "completed"
        }
    )
    # step 0 与 step 1 各完成一次；step 0 未在恢复时被重复记录。
    assert completed_indices == [0, 1]
    # 整条恢复历史满足 append-only 排序不变量。
    assert_monotonic_order(records)
    # 最新 checkpoint ref 指向 durable checkpoint。
    assert latest_checkpoint_ref(records) is not None

    clear_checkpoint(path=checkpoint_path)
