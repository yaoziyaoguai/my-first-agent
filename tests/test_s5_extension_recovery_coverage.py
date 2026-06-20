"""S5-G10 extension-boundary recovery coverage 测试。

证明 durable recovery 在 governed task 涉及既有受控扩展（read-only SubAgent 委派 +
MCP 工具）时仍成立：

- 扩展事件经既有 mediator/evidence 路径记录（delegation_log / tool_execution_log）；
- checkpoint 恢复后扩展事件存活；
- ledger 与恢复后的 replay chain 仍对齐（AC-8）、checkpoint-ledger 一致（AC-4）；
- Scheduler 保持 dormant（TD-008 / AC-6 non-goal）：S5 ledger/recovery 模块不引用
  ActionScheduler。

不实现 Scheduler 产品化、full MCP discovery 或 writable SubAgent（explicit non-goal）。
"""

from __future__ import annotations

import importlib
import inspect

from agent.checkpoint import (
    clear_checkpoint,
    load_checkpoint_to_state,
    save_checkpoint,
)
from agent.ledger_audit_alignment import align_ledger_with_replay
from agent.state import create_agent_state
from agent.task_ledger_cooperation import (
    check_recovery_consistency,
    record_checkpoint_boundary,
    record_evidence_ref,
)
from agent.task_ledger_store import TaskLedger
from agent.task_orchestration import (
    accept_governed_plan,
    advance_governed_task_if_ready,
    receive_governed_task,
)
from agent.task_replay_chain import build_replay_chain
from agent.task_state_model import build_governed_task_state
from config import STEP_COMPLETION_THRESHOLD


def _extension_plan() -> dict:
    return {
        "goal": "s5 extension recovery demo",
        "steps": [
            {
                "step_id": "sx-1",
                "title": "Use governed extension",
                "description": "delegate + mcp tool",
                "step_type": "read",
            },
            {
                "step_id": "sx-2",
                "title": "Finish",
                "description": "complete",
                "step_type": "report",
            },
        ],
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


def test_s5_recovery_preserves_governed_extension_events(tmp_path):
    checkpoint_path = tmp_path / "s5-extension-checkpoint.json"
    ledger_path = tmp_path / "s5-extension-ledger.jsonl"
    task_id = "s5-extension-task"
    ledger = TaskLedger(ledger_path)

    # --- Phase 1: step 0 使用 governed 扩展（read-only SubAgent 委派 + MCP 工具）---
    state = create_agent_state(system_prompt="S5 extension recovery test")
    state.memory.session_id = "s5-extension-session"
    receive_governed_task(
        state, user_goal="S5 extension recovery demo", plan_payload=_extension_plan()
    )
    accept_governed_plan(state)

    # 既有 mediator/evidence 路径：MCP 工具结果 + read-only SubAgent 委派。
    state.task.tool_execution_log["mcp-tool-1"] = {
        "tool": "mcp_search",
        "status": "executed",
        "input": {"target": "external-doc"},
        "result": "search-result",
        "step_index": 0,
    }
    state.task.delegation_log.append(
        {
            "delegation_id": "del-1",
            "subagent_name": "reviewer",
            "status": "delegated",
            "step_index": 0,
            "stop_reason": "read-only second opinion",
            "adjudication_action": "accept",
        }
    )
    _mark_step_complete(state, tool_use_id="meta-0", summary="extension step done")

    # 把 replay chain 的事件记为 ledger evidence ref（经既有 replay chain 对齐）。
    chain = build_replay_chain(state)
    assert any(event.kind == "delegation" for event in chain.events)
    assert any(event.ref_id == "mcp-tool-1" for event in chain.events)
    for event in chain.events:
        record_evidence_ref(
            ledger,
            task_id=task_id,
            evidence_ref=event.ref_id,
            evidence_kind=event.kind,
            safe_summary=event.name,
            recorded_at="t1",
        )
    save_checkpoint(state, source="s5.extension.step0", path=checkpoint_path)
    record_checkpoint_boundary(
        ledger,
        build_governed_task_state(state),
        task_id=task_id,
        checkpoint_ref=str(checkpoint_path),
        checkpoint_source="step0_complete",
        recorded_at="t2",
    )
    advance_governed_task_if_ready(state)
    save_checkpoint(state, source="s5.extension.step0-advanced", path=checkpoint_path)
    del state

    # --- Phase 2: 从 checkpoint+ledger 重载，验证扩展事件存活且对齐 ---
    resumed = create_agent_state(system_prompt="S5 extension recovery test")
    assert load_checkpoint_to_state(resumed, path=checkpoint_path) is True

    resumed_chain = build_replay_chain(resumed)
    # 扩展事件经 checkpoint 恢复后仍存在（既有 mediator/evidence 路径持久化）。
    assert any(
        event.kind == "delegation" and event.ref_id == "del-1"
        for event in resumed_chain.events
    )
    assert any(event.ref_id == "mcp-tool-1" for event in resumed_chain.events)

    reopened = TaskLedger(ledger_path)
    alignment = align_ledger_with_replay(resumed_chain, reopened.read_all())
    assert alignment.coherent, [
        issue for issue in (alignment.unaligned_evidence_refs, alignment.unaligned_step_refs)
    ]

    report = check_recovery_consistency(
        reopened.read_all(),
        checkpoint_ref_exists=checkpoint_path.exists(),
        governed_state=build_governed_task_state(resumed),
    )
    assert report.ok, [issue.kind for issue in report.issues]

    clear_checkpoint(path=checkpoint_path)


def test_s5_recovery_modules_do_not_activate_scheduler():
    # Scheduler 保持 dormant（TD-008 / S5 non-goal）：S5 ledger/recovery 模块不得引用
    # ActionScheduler / action_scheduler。
    s5_modules = (
        "agent.task_ledger",
        "agent.task_ledger_store",
        "agent.task_ledger_cooperation",
        "agent.ledger_audit_alignment",
    )
    for module_name in s5_modules:
        source = inspect.getsource(importlib.import_module(module_name))
        assert "ActionScheduler" not in source, f"{module_name} references ActionScheduler"
        assert "action_scheduler" not in source, f"{module_name} references action_scheduler"
