"""S3 audit fix (H1): SubAgent 真实 runtime delegation path 接入 delegation evidence。

独立 S3 审计发现：真实 runtime path `agent/subagent_inline.py:execute_subagent_delegation`
在成功委派后**没有**调用 `record_delegation_run`，导致 SubAgent second-opinion 结果不进
`state.task.delegation_log` / checkpoint / evidence report——该 seam 之前只有测试直接调用，
真实运行时委派不产生 extension evidence（审计 H1）。

本测试钉住修复后的行为：真实 runtime 委派函数在拿到 `state` 时，把委派安全投影写入
`delegation_log`，能跨 checkpoint→resume 保真，并在 evidence report 中复盘
（`extensions.delegations:N`）。parent-mediated 不变——只记录已发生的 parent adjudication，
不赋予 child 任何 tool/provider/memory 旁路。
"""
from __future__ import annotations

from agent import subagent_inline
from agent.checkpoint import clear_checkpoint, load_checkpoint_to_state, save_checkpoint
from agent.state import create_agent_state
from agent.task_evidence_report import build_task_evidence_report


def test_runtime_delegation_records_into_delegation_log_and_evidence():
    """execute_subagent_delegation(state=...) 成功委派后写入 delegation_log + evidence report。"""
    state = create_agent_state(system_prompt="S3 runtime delegation evidence")
    state.memory.session_id = "s3-runtime-delegation-evidence-session"

    rendered = subagent_inline.execute_subagent_delegation(
        "demo-stat",
        "Audit whether fixture gap evidence satisfies AC",
        delegation_reason="second opinion",
        on_runtime_event=None,
        state=state,
    )
    # 用户可见结果不回归（仍渲染非空字符串）
    assert isinstance(rendered, str) and rendered.strip()
    # 真实 runtime path 现在把委派安全投影写入 task-state delegation_log（审计 H1 修复）
    assert len(state.task.delegation_log) == 1
    entry = state.task.delegation_log[0]
    assert entry["subagent_name"], "delegation 投影应含 subagent_name"
    assert entry["adjudication_action"], "delegation 投影应含 parent adjudication action"
    # evidence report 可复盘 extension 决策
    report = build_task_evidence_report(state)
    assert any("extensions.delegations:1" in e for e in report.evidence_events), (
        f"evidence report 应呈现 runtime 委派 extension 计数，实际={report.evidence_events}"
    )


def test_runtime_delegation_without_state_is_backward_compatible():
    """不传 state 时行为同旧版（只渲染、不记录）——既有 CLI / 测试调用不回归。"""
    rendered = subagent_inline.execute_subagent_delegation(
        "demo-stat",
        "no-state delegation",
        delegation_reason="legacy call",
        on_runtime_event=None,
    )
    assert isinstance(rendered, str) and rendered.strip()


def test_runtime_delegation_survives_checkpoint_resume(tmp_path):
    """runtime 委派写入的 delegation_log 跨 checkpoint→resume 保真（可恢复审计）。"""
    state = create_agent_state(system_prompt="S3 runtime delegation checkpoint")
    state.memory.session_id = "s3-runtime-delegation-checkpoint-session"
    subagent_inline.execute_subagent_delegation(
        "demo-stat",
        "audit gap evidence",
        delegation_reason="second opinion",
        on_runtime_event=None,
        state=state,
    )
    assert len(state.task.delegation_log) == 1

    checkpoint_path = tmp_path / "s3-runtime-delegation-checkpoint.json"
    save_checkpoint(state, source="tests.s3.runtime_delegation", path=checkpoint_path)
    resumed = create_agent_state(system_prompt="S3 runtime delegation checkpoint")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path) is True
    assert len(resumed.task.delegation_log) == 1
    assert resumed.task.delegation_log[0]["subagent_name"]
    clear_checkpoint(path=checkpoint_path)
