from __future__ import annotations

from agent.state import create_agent_state
from agent.task_context import (
    build_task_execution_context,
    record_task_memory_boundary_evidence,
)
from agent.task_orchestration import receive_governed_task
from agent.task_state_model import GovernedTaskLifecycle


def _plan() -> dict:
    return {
        "goal": "repo-governed improvement task",
        "thinking": "audit then verify",
        "steps": [
            {
                "step_id": "step-1",
                "title": "inspect docs",
                "description": "read current S2 docs",
                "step_type": "read",
            },
            {
                "step_id": "step-2",
                "title": "report",
                "description": "write evidence summary",
                "step_type": "report",
            },
        ],
    }


def test_task_execution_context_includes_task_state_and_memory_boundary():
    state = create_agent_state(system_prompt="test")
    state.memory.session_id = "session-1"
    state.memory.working_summary = "Earlier context summary."
    state.memory.memory_store_reference = {"store": "fake", "root": "redacted"}
    state.task.pending_retain_proposals = [{"proposal_id": "p1"}]
    assert receive_governed_task(
        state,
        user_goal="repair one focused S2 gap",
        plan_payload=_plan(),
    ).allowed

    package = build_task_execution_context(state)

    assert package.task.lifecycle is GovernedTaskLifecycle.WAITING
    assert package.memory_boundary.task_scope_id.startswith("task-")
    assert "repair one focused S2 gap" not in package.memory_boundary.task_scope_id
    assert package.memory_boundary.has_working_summary is True
    assert package.memory_boundary.has_memory_store_reference is True
    assert package.memory_boundary.pending_retain_proposals == 1
    assert package.provider_callable is True
    all_text = "\n".join(
        msg["content"]
        for msg in package.model_messages
        if isinstance(msg.get("content"), str)
    )
    assert "Earlier context summary." in all_text
    assert "[当前任务] repo-governed improvement task" in all_text


def test_resume_context_keeps_large_tool_result_provider_callable(tmp_path):
    from agent.checkpoint import load_checkpoint_to_state, save_checkpoint
    from agent.evidence_persistence import MAX_TOOL_RESULT_BYTES

    checkpoint_path = tmp_path / "checkpoint.json"
    huge = "x" * (MAX_TOOL_RESULT_BYTES * 3)
    src = create_agent_state(system_prompt="test")
    src.task.status = "running"
    src.task.user_goal = "repair one focused S2 gap"
    src.task.current_plan = _plan()
    src.conversation.messages = [
        {"role": "user", "content": "read large file"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "T1", "name": "read_file", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "T1", "content": huge},
            ],
        },
    ]
    save_checkpoint(src, source="tests.s2.task_context", path=checkpoint_path)

    dst = create_agent_state(system_prompt="test")
    assert load_checkpoint_to_state(dst, path=checkpoint_path)
    package = build_task_execution_context(dst)

    assert package.provider_callable is True
    assert package.provider_callable_issues == ()
    tool_result_blocks = [
        block
        for msg in package.model_messages
        if isinstance(msg.get("content"), list)
        for block in msg["content"]
        if isinstance(block, dict) and block.get("type") == "tool_result"
    ]
    assert tool_result_blocks
    assert all("content" in block for block in tool_result_blocks)
    assert any("content_persisted=false" in block["content"] for block in tool_result_blocks)
    assert huge not in str(package.model_messages)


def test_memory_boundary_evidence_is_safe_and_task_scoped():
    state = create_agent_state(system_prompt="test")
    state.memory.session_id = "session-1"
    state.memory.working_summary = "summary with no raw secret"
    state.task.status = "running"
    state.task.user_goal = "repair one focused S2 gap"
    state.task.current_plan = _plan()
    package = build_task_execution_context(state)
    calls: list[dict] = []

    def fake_record_evidence(**kwargs):
        calls.append(kwargs)
        return kwargs

    envelope = record_task_memory_boundary_evidence(
        package,
        record_evidence_fn=fake_record_evidence,
    )

    assert envelope["subsystem"] == "memory"
    assert envelope["operation"] == "task_context.build_execution_context"
    assert envelope["status"] == "ok"
    assert envelope["content_persisted"] is False
    assert envelope["metadata"]["task_scope_id"].startswith("task-")
    assert envelope["metadata"]["provider_callable"] is True
    assert "summary with no raw secret" not in str(envelope)
    assert calls == [envelope]
