"""G2 — Tool success Golden E2E (characterization, flag off).

Drives ``run_local_demo()`` end-to-end (the same smoke harness used by
``tests/smoke/test_first_usable_task_e2e.py``) and asserts the tool result
envelope + trace event shape. Golden E2E G2 is the user-visible floor that any
window must keep green.
"""

from __future__ import annotations

from agent.local_demo import run_local_demo


def test_g2_local_demo_completes_with_tool_execution_envelope():
    """G2: run_local_demo() → 工具动作 → executed envelope + tool_result trace。"""
    result = run_local_demo("create a smoke test note")

    assert result.provider == "fake"
    assert result.task == "create a smoke test note"
    assert len(result.steps) >= 1

    step = result.steps[0]
    assert step.action.tool_name == "demo.write_demo_note"
    assert step.envelope.status == "executed"
    assert step.envelope.content_length > 0
    assert len(step.trace_event.metadata) > 0

    # user-visible final answer
    assert len(result.final_answer) > 0
    assert "demo note" in result.final_answer or "wrote" in result.final_answer

    # trace events: tool_result + completion
    trace_names = [e.name for e in result.trace_events]
    assert any("tool_result" in n for n in trace_names), (
        f"trace events 应包含 tool_result，实际: {trace_names}"
    )
    assert "demo.complete" in trace_names
