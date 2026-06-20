"""S5-G06 ledger-aware audit/replay 对齐测试。

锁定 AC-8：恢复后的 task 必须仍有可审计、ref 一致的 task/evidence/ledger 视图。
``align_ledger_with_replay`` 把 S4 ``ReplayChain`` 的 ref_ids 与 ledger 的
evidence/step/checkpoint refs 对齐，证明三者连贯；``record_evidence_ref`` 提供把
replay chain 的 tool 事件记录为 ledger evidence ref 的 seam。S4 的
``build_replay_chain``/``render_replay_summary`` 契约不变（本层只读取、不修改它们）。

这些测试在 alignment 模块 / record_evidence_ref 实现前必须失败（RED）。
"""

from __future__ import annotations

import dataclasses

from agent.ledger_audit_alignment import (
    LedgerAuditAlignment,
    align_ledger_with_replay,
)
from agent.state import create_agent_state
from agent.task_ledger import (
    CheckpointRefRecord,
    EvidenceRefRecord,
    StepProgressRecord,
)
from agent.task_ledger_cooperation import record_evidence_ref
from agent.task_ledger_store import TaskLedger
from agent.task_orchestration import accept_governed_plan, receive_governed_task
from agent.task_replay_chain import build_replay_chain

_SECRET = "sk-leaksurvives123456"


def _state_with_plan_and_tools():
    state = create_agent_state(system_prompt="S5 audit alignment test")
    state.memory.session_id = "s5-audit-alignment-session"
    receive_governed_task(
        state,
        user_goal="S5 audit alignment demo",
        plan_payload={
            "goal": "s5 audit alignment",
            "steps": [
                {"step_id": "sa", "title": "step A", "description": "a", "step_type": "read"},
                {"step_id": "sb", "title": "step B", "description": "b", "step_type": "edit"},
            ],
        },
    )
    accept_governed_plan(state)
    state.task.tool_execution_log["t1"] = {
        "tool": "read_file",
        "status": "executed",
        "input": {"target": "x"},
        "result": "r1",
        "step_index": 0,
    }
    state.task.tool_execution_log["t2"] = {
        "tool": "apply_patch",
        "status": "executed",
        "input": {"target": "y"},
        "result": "r2",
        "step_index": 1,
    }
    return state


def test_replay_chain_exposes_step_and_tool_refs():
    chain = build_replay_chain(_state_with_plan_and_tools())
    refs = {event.ref_id for event in chain.events}
    # plan step_ids + tool_use_ids 都出现在 replay chain 的 ref_ids 中。
    assert {"sa", "sb", "t1", "t2"} <= refs


def test_record_evidence_ref_appends_and_redacts(tmp_path):
    ledger = TaskLedger(tmp_path / "l.jsonl")
    persisted = record_evidence_ref(
        ledger,
        task_id="t1",
        evidence_ref="t1",
        evidence_kind="tool",
        safe_summary=f"preview {_SECRET}",
        recorded_at="r1",
    )
    assert isinstance(persisted, EvidenceRefRecord)
    assert persisted.evidence_ref == "t1"
    # safe_summary 经 ledger.append 内部 redact。
    assert _SECRET not in (persisted.safe_summary or "")
    records = ledger.read_all()
    assert isinstance(records[0], EvidenceRefRecord)


def test_align_coherent_when_ledger_refs_match_replay(tmp_path):
    chain = build_replay_chain(_state_with_plan_and_tools())
    ledger = TaskLedger(tmp_path / "l.jsonl")
    # 把 replay chain 的 tool 事件记录为 ledger evidence ref —— 完全对齐。
    for tool_event in chain.tool_events:
        record_evidence_ref(
            ledger,
            task_id="t1",
            evidence_ref=tool_event.ref_id,
            evidence_kind="tool",
            safe_summary=tool_event.name,
            recorded_at="r1",
        )
    alignment = align_ledger_with_replay(chain, ledger.read_all())
    assert isinstance(alignment, LedgerAuditAlignment)
    assert alignment.coherent
    assert alignment.unaligned_evidence_refs == ()
    assert alignment.unaligned_step_refs == ()
    assert alignment.replay_event_count == len(chain.events)


def test_align_flags_unaligned_evidence_ref(tmp_path):
    chain = build_replay_chain(_state_with_plan_and_tools())
    ledger = TaskLedger(tmp_path / "l.jsonl")
    # 记录一个 replay chain 中不存在的 evidence ref。
    record_evidence_ref(
        ledger, task_id="t1", evidence_ref="ghost-evidence",
        evidence_kind="tool", safe_summary=None, recorded_at="r1",
    )
    alignment = align_ledger_with_replay(chain, ledger.read_all())
    assert not alignment.coherent
    assert "ghost-evidence" in alignment.unaligned_evidence_refs


def test_align_flags_unaligned_step_ref(tmp_path):
    chain = build_replay_chain(_state_with_plan_and_tools())
    ledger = TaskLedger(tmp_path / "l.jsonl")
    ledger.append(StepProgressRecord("t1", 1, "r1", 0, "ghost-step", "completed", None))
    alignment = align_ledger_with_replay(chain, ledger.read_all())
    assert not alignment.coherent
    assert "ghost-step" in alignment.unaligned_step_refs


def test_align_reports_checkpoint_ref(tmp_path):
    chain = build_replay_chain(_state_with_plan_and_tools())
    ledger = TaskLedger(tmp_path / "l.jsonl")
    ledger.append(CheckpointRefRecord("t1", 1, "r1", "/tmp/c.json", "step_boundary", "running"))
    alignment = align_ledger_with_replay(chain, ledger.read_all())
    assert alignment.ledger_checkpoint_ref == "/tmp/c.json"
    assert alignment.coherent  # 无 evidence/step ref，不构成不对齐


def test_alignment_is_structurally_secret_free():
    # AC-8 + 避免原始 payload：alignment 只持有 refs/counts/checkpoint_ref，无 summary 字段。
    fields = {f.name for f in dataclasses.fields(LedgerAuditAlignment)}
    forbidden = {"payload", "summary", "safe_summary", "preview", "secret", "token"}
    assert not (fields & forbidden)


def test_replay_chain_still_builds_on_ledger_equipped_state(tmp_path):
    # S4 replay 契约不受 ledger 存在影响（本层只读取 chain，不改 build_replay_chain）。
    state = _state_with_plan_and_tools()
    chain = build_replay_chain(state)
    assert len(chain.events) > 0
    ledger = TaskLedger(tmp_path / "l.jsonl")
    for tool_event in chain.tool_events:
        record_evidence_ref(
            ledger, task_id="t1", evidence_ref=tool_event.ref_id,
            evidence_kind="tool", safe_summary=None, recorded_at="r1",
        )
    # 再次构建 chain 仍一致（ledger 记录未污染 task-state 投影）。
    assert build_replay_chain(state).events == chain.events
