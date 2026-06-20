"""S4-G05 evidence verification / consistency check 测试（AC-5）。

验证 evidence verifier 对 replay chain 做完整/自洽/有序/可复放校验：
- 完整 evidence（与源 state 一致）→ 通过；
- 残缺（删一条 tool）/ 篡改（status 与计数矛盾）/ 乱序 / 空链 / 重复 ref → 对应失败 reason。

判据（`S4_FIDELITY_CONTRACT.md §5`）：complete / self_consistent / ordered / replayable。
"""
from __future__ import annotations

from dataclasses import replace

from agent.evidence_verifier import (
    VerificationReport,
    verify_evidence,
    verify_replay_chain,
)
from agent.state import create_agent_state
from agent.task_replay_chain import ReplayChain, build_replay_chain


def _good_state() -> object:
    state = create_agent_state(system_prompt="s4-test", model_name="fake")
    state.task.user_goal = "audit/replay reference task"
    state.task.current_plan = {
        "goal": "g",
        "thinking": "t",
        "steps": [
            {"step_id": "s1", "title": "Inspect", "description": "read", "step_type": "read"},
            {"step_id": "s2", "title": "Report", "description": "report", "step_type": "report"},
        ],
    }
    state.task.status = "running"
    state.task.current_step_index = 1
    state.task.tool_execution_log = {
        "toolu_a": {
            "tool": "repo_doc_reader",
            "status": "executed",
            "input": {"target": "gap-1"},
            "result": "ok",
            "step_index": 0,
        },
        "toolu_b": {
            "tool": "read_file",
            "status": "blocked_by_policy",
            "input": {"path": "x"},
            "result": "blocked",
            "step_index": 1,
        },
    }
    state.task.delegation_log = [
        {
            "delegation_id": "del_1",
            "subagent_name": "auditor",
            "status": "delegated",
            "adjudication_action": "accept",
            "step_index": 1,
        },
    ]
    return state


def _finding(report: VerificationReport, check: str) -> tuple[bool, str]:
    for f in report.findings:
        if f.check == check:
            return f.passed, f.reason
    raise AssertionError(f"缺少 {check} finding: {report.findings}")


# ═══════════════════════════════════════════════════════
# A. 完整 evidence → 通过
# ═══════════════════════════════════════════════════════


def test_verify_evidence_passes_for_complete_state():
    """与源 state 一致的完整 chain → 四项校验全通过。"""
    report = verify_evidence(_good_state())
    assert isinstance(report, VerificationReport)
    assert report.ok is True
    for check in ("complete", "self_consistent", "ordered", "replayable"):
        passed, reason = _finding(report, check)
        assert passed, f"{check} 应通过，实际 reason={reason}"


# ═══════════════════════════════════════════════════════
# B. 残缺：删一条 tool entry → chain_incomplete
# ═══════════════════════════════════════════════════════


def test_verifier_detects_missing_tool_entry():
    state = _good_state()
    full_chain = build_replay_chain(state)
    # 构造残缺 chain：移除 toolu_a 这条 tool 事件
    truncated_events = tuple(e for e in full_chain.events if e.ref_id != "toolu_a")
    truncated = replace(full_chain, events=truncated_events)

    report = verify_replay_chain(
        truncated,
        expected_tool_use_ids=["toolu_a", "toolu_b"],
        expected_delegation_ids=["del_1"],
    )
    assert report.ok is False
    passed, reason = _finding(report, "complete")
    assert passed is False
    assert reason == "chain_incomplete"


def test_verifier_detects_missing_delegation_entry():
    state = _good_state()
    full_chain = build_replay_chain(state)
    truncated_events = tuple(e for e in full_chain.events if e.ref_id != "del_1")
    truncated = replace(full_chain, events=truncated_events)

    report = verify_replay_chain(
        truncated,
        expected_tool_use_ids=["toolu_a", "toolu_b"],
        expected_delegation_ids=["del_1"],
    )
    assert report.ok is False
    _, reason = _finding(report, "complete")
    assert reason == "chain_incomplete"


# ═══════════════════════════════════════════════════════
# C. 篡改：status 与计数矛盾 → count_mismatch
# ═══════════════════════════════════════════════════════


def test_verifier_detects_count_mismatch_from_status_tamper():
    """把一条 executed tool 篡改为 failed → executed/failed 计数与源不符 → count_mismatch。"""
    state = _good_state()
    full_chain = build_replay_chain(state)
    tampered_events = tuple(
        replace(e, status="failed") if e.ref_id == "toolu_a" else e
        for e in full_chain.events
    )
    tampered = replace(full_chain, events=tampered_events)

    # 源状态：executed=1 (toolu_a), blocked_by_policy=1 (toolu_b)
    report = verify_replay_chain(
        tampered,
        expected_tool_use_ids=["toolu_a", "toolu_b"],
        expected_delegation_ids=["del_1"],
        expected_tool_counts={"executed": 1, "blocked_by_policy": 1, "failed": 0},
    )
    assert report.ok is False
    _, reason = _finding(report, "self_consistent")
    assert reason == "count_mismatch"


# ═══════════════════════════════════════════════════════
# D. 乱序：seq 非单调 → sequence_disorder
# ═══════════════════════════════════════════════════════


def test_verifier_detects_sequence_disorder():
    """打乱 seq 单调性 → sequence_disorder。"""
    state = _good_state()
    full_chain = build_replay_chain(state)
    # 反转 events 顺序但保留原 seq → seq 序列不再单调递增
    reversed_events = tuple(reversed(full_chain.events))
    disordered = replace(full_chain, events=reversed_events)

    report = verify_replay_chain(
        disordered,
        expected_tool_use_ids=["toolu_a", "toolu_b"],
        expected_delegation_ids=["del_1"],
    )
    assert report.ok is False
    _, reason = _finding(report, "ordered")
    assert reason == "sequence_disorder"


# ═══════════════════════════════════════════════════════
# E. 空链 → not_replayable
# ═══════════════════════════════════════════════════════


def test_verifier_empty_chain_not_replayable():
    empty_chain = ReplayChain(task_scope_id="x", lifecycle="idle", events=())
    report = verify_replay_chain(empty_chain)
    assert report.ok is False
    _, reason = _finding(report, "replayable")
    assert reason == "not_replayable"


# ═══════════════════════════════════════════════════════
# F. 重复 ref → duplicate_ref
# ═══════════════════════════════════════════════════════


def test_verifier_detects_duplicate_tool_ref():
    state = _good_state()
    full_chain = build_replay_chain(state)
    # 复制 toolu_a 一份追加（同 ref_id 出现两次）
    dup_events = full_chain.events + tuple(
        e for e in full_chain.events if e.ref_id == "toolu_a"
    )
    duplicated = replace(full_chain, events=dup_events)

    report = verify_replay_chain(
        duplicated,
        expected_tool_use_ids=["toolu_a", "toolu_b"],
        expected_delegation_ids=["del_1"],
    )
    assert report.ok is False
    _, reason = _finding(report, "self_consistent")
    assert reason == "duplicate_ref"
