"""S4-G02 replay-faithful evidence chain 投影测试（redacted-faithful model）。

验证 build_replay_chain(state) 把 task-state 既有字段（tool_execution_log /
delegation_log / current_plan / current_step_index）投影成一条**有序、可复放**的
ReplayChain，超出 S3 的「tools.executed:N」标签级（消化 TD-001）。

边界（S4_FIDELITY_CONTRACT.md §2/§3）：
- 只读投影 state.task，不写 state、不改 checkpoint。
- safe-summary 粒度：input/output preview 截断到 PREVIEW_MAX。
- secret redaction 的**强制断言**属 G03；本测试只验证投影/排序/截断/可重建。
"""
from __future__ import annotations

from agent.state import create_agent_state
from agent.task_replay_chain import (
    PREVIEW_MAX,
    ReplayChain,
    ReplayEvent,
    build_replay_chain,
)


def _plan() -> dict:
    return {
        "goal": "audit/replay reference task",
        "thinking": "inspect evidence, take second opinion, adjudicate",
        "steps": [
            {
                "step_id": "s1",
                "title": "Inspect evidence",
                "description": "read fixture evidence",
                "step_type": "read",
            },
            {
                "step_id": "s2",
                "title": "Second opinion",
                "description": "subagent audit",
                "step_type": "edit",
            },
            {
                "step_id": "s3",
                "title": "Report",
                "description": "adjudicate and report",
                "step_type": "report",
            },
        ],
    }


def _state_with_chain() -> object:
    """构造一条含 tool（2）+ delegation（1）+ plan（3 steps）的 governed task state。"""
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    state.task.user_goal = "audit/replay reference task"
    state.task.current_plan = _plan()
    state.task.status = "running"
    state.task.current_step_index = 1  # step0 advanced, step1 in_progress
    state.task.tool_execution_log = {
        "toolu_read_1": {
            "tool": "repo_doc_reader",
            "status": "executed",
            "input": {"target": "fixture-gap-1"},
            "result": "gap-1 satisfied: evidence present",
            "step_index": 0,
        },
        "toolu_blocked_1": {
            "tool": "read_file",
            "status": "blocked_by_policy",
            "input": {"path": "config/config.yaml"},
            "result": "blocked: sensitive path",
            "step_index": 1,
        },
    }
    state.task.delegation_log = [
        {
            "delegation_id": "del_1",
            "subagent_name": "repo_gap_auditor",
            "status": "delegated",
            "stop_reason": "audit_complete",
            "execution_mode": "inline_l0",
            "adjudication_action": "accept",
            "confidence": 0.8,
            "tools_executed": 1,
            "tools_denied": 0,
            "step_index": 1,
        },
    ]
    return state


# ═══════════════════════════════════════════════════════
# A. 投影：tool / delegation / decision 三类齐全
# ═══════════════════════════════════════════════════════


def test_build_replay_chain_projects_all_three_kinds():
    """replay chain 必须把 tool_execution_log + delegation_log + plan steps 全部投影。

    中文注释：这是 AC-2 的核心——chain 不能再只是「tools.executed:N」标签，
    必须暴露实际的 tool 名/status/input preview/output preview + 委派 adjudication。
    """
    state = _state_with_chain()
    chain = build_replay_chain(state)

    assert isinstance(chain, ReplayChain)
    assert len(chain.tool_events) == 2
    assert len(chain.delegation_events) == 1
    # plan 有 3 步，全部作为 decision 锚投影（advanced / in_progress / planned）
    assert len(chain.decision_events) == 3


def test_tool_events_carry_name_status_previews_and_ref():
    """tool event 必须可重建：哪个 tool、什么 status、safe input/output preview、ref_id。"""
    state = _state_with_chain()
    chain = build_replay_chain(state)

    by_ref = {e.ref_id: e for e in chain.tool_events}
    read_evt = by_ref["toolu_read_1"]
    assert read_evt.kind == "tool"
    assert read_evt.name == "repo_doc_reader"
    assert read_evt.status == "executed"
    assert read_evt.policy_outcome == "allow"
    assert "fixture-gap-1" in read_evt.input_preview
    assert "gap-1 satisfied" in read_evt.output_preview

    blocked_evt = by_ref["toolu_blocked_1"]
    assert blocked_evt.status == "blocked_by_policy"
    assert blocked_evt.policy_outcome == "reject"


def test_delegation_events_carry_adjudication():
    """delegation event 必须暴露 subagent 名 + adjudication_action（可复盘委派决策）。"""
    state = _state_with_chain()
    chain = build_replay_chain(state)

    del_evt = chain.delegation_events[0]
    assert del_evt.kind == "delegation"
    assert del_evt.ref_id == "del_1"
    assert del_evt.name == "repo_gap_auditor"
    assert del_evt.policy_outcome == "accept"


# ═══════════════════════════════════════════════════════
# B. 有序：seq 单调，按 step_index + kind 顺序
# ═══════════════════════════════════════════════════════


def test_chain_events_are_ordered_with_monotonic_seq():
    """chain 必须有序：seq 从 0 单调递增；同 step 内 decision < tool < delegation。"""
    state = _state_with_chain()
    chain = build_replay_chain(state)

    seqs = [e.seq for e in chain.events]
    assert seqs == list(range(len(chain.events))), f"seq 必须从 0 单调递增，实际 {seqs}"

    # step_index 非递减
    step_indices = [e.step_index for e in chain.events]
    assert step_indices == sorted(step_indices)

    # 同一 step_index=1 内：decision(s2) 早于 tool(blocked) 早于 delegation(del_1)
    step1 = [e for e in chain.events if e.step_index == 1]
    kinds_in_order = [e.kind for e in step1]
    # decision 必须在 tool/delegation 之前
    assert kinds_in_order.index("decision") < kinds_in_order.index("tool")
    assert kinds_in_order.index("tool") < kinds_in_order.index("delegation")


# ═══════════════════════════════════════════════════════
# C. safe-summary 粒度：preview 截断
# ═══════════════════════════════════════════════════════


def test_previews_are_truncated_to_safe_summary_length():
    """超长 input/result 的 preview 必须截断到 PREVIEW_MAX（safe-summary 粒度）。"""
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    long_blob = "X" * (PREVIEW_MAX * 5)
    state.task.tool_execution_log = {
        "toolu_long": {
            "tool": "read_file",
            "status": "executed",
            "input": {"target": long_blob},
            "result": long_blob,
            "step_index": 0,
        },
    }
    chain = build_replay_chain(state)
    evt = chain.tool_events[0]
    assert len(evt.input_preview) <= PREVIEW_MAX
    assert len(evt.output_preview) <= PREVIEW_MAX
    # 截断后不应包含完整 blob
    assert long_blob not in evt.input_preview
    assert long_blob not in evt.output_preview


# ═══════════════════════════════════════════════════════
# D. 可重建：仅凭 chain 可重导 governed path 摘要
# ═══════════════════════════════════════════════════════


def test_chain_is_reconstructable_without_raw_state():
    """仅凭 chain（丢弃原始 state）即可回答「agent 做了什么、什么顺序、什么结果」。"""
    chain = build_replay_chain(_state_with_chain())

    # 重建：tool 调用顺序 + 各自 status + 是否有委派 + adjudication
    tool_seq = [(e.name, e.status) for e in chain.events if e.kind == "tool"]
    assert tool_seq == [("repo_doc_reader", "executed"), ("read_file", "blocked_by_policy")]
    delegations = [(e.name, e.policy_outcome) for e in chain.delegation_events]
    assert delegations == [("repo_gap_auditor", "accept")]


def test_empty_state_yields_empty_chain_not_crash():
    """空 state（无 plan/tool/delegation）应得到空 chain，不 crash。"""
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    chain = build_replay_chain(state)
    assert chain.events == ()
    assert chain.tool_events == ()
    assert chain.delegation_events == ()


# ═══════════════════════════════════════════════════════
# E. TaskEvidenceReport 携带 replay chain（超出摘要级）
# ═══════════════════════════════════════════════════════


def test_task_evidence_report_carries_replay_chain():
    """build_task_evidence_report 必须把 replay_chain 投影进报告（向后兼容默认空）。"""
    from agent.task_evidence_report import build_task_evidence_report

    state = _state_with_chain()
    report = build_task_evidence_report(state)
    chain_events = getattr(report, "replay_chain_events", None)
    assert chain_events is not None, "TaskEvidenceReport 必须携带 replay_chain_events"
    assert len(chain_events) >= 3  # 至少 tool+delegation+decision
    assert all(isinstance(e, ReplayEvent) for e in chain_events)
