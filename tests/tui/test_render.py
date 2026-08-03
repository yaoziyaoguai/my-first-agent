from __future__ import annotations

from dataclasses import replace

from agent.runtime.contracts import (
    ApprovalRequest,
    ConversationState,
    RecordedRunResult,
    RecoveryRequest,
    RunStatus,
    SubmitMessage,
    ToolCall,
)
from agent.runtime.state import (
    accept_action,
    mark_executing,
    pause_for_approval,
    pause_for_recovery,
    start_tool_batch,
)
from agent.tui.render import SafeDisplayTooLargeError, project, run_status_label, safe_display


def _approval_state():
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="c1", action_seq=1, expected_revision=0, run_id="r", message="hi"
        ),
    ).state
    batched = start_tool_batch(started, (ToolCall("call-1", "write_file", {}),))
    return pause_for_approval(
        batched,
        ApprovalRequest(
            request_id="a1", run_id="r", tool_call_id="call-1", binding_digest="b", preview="write"
        ),
    )


def _recovery_state():
    from agent.runtime.state import mark_executing

    # 切到 EXECUTING 再进入 recovery：先 approve 走一次 runnable+executing。
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="c1", action_seq=1, expected_revision=0, run_id="r2", message="hi"
        ),
    ).state
    batched = start_tool_batch(started, (ToolCall("call-2", "write_file", {}),))
    executing = mark_executing(
        batched, tool_call_id="call-2", intent_digest="d", idempotency_key="k"
    )
    return pause_for_recovery(
        executing,
        RecoveryRequest(
            request_id="rec1", run_id="r2", tool_call_id="call-2", binding_digest="d", summary="u"
        ),
    )


def test_safe_display_escapes_ansi_bidi_and_controls() -> None:
    raw = "clean\x1b[2Jtext‮override\x00\x9bend"
    out = safe_display(raw)
    assert "\x1b" not in out
    assert "\x9b" not in out
    assert "\x00" not in out
    assert "‮" not in out
    assert "<U+001B>" in out
    assert "<U+202E>" in out
    assert "<U+009B>" in out
    assert "<U+0000>" in out
    assert "clean" in out and "text" in out and "override" in out and "end" in out


def test_safe_display_keeps_newlines_and_tabs() -> None:
    out = safe_display("line1\nline2\tend")
    assert "\n" in out and "\t" in out


def test_safe_display_cap_rejects_without_truncation() -> None:
    with __import__("pytest").raises(SafeDisplayTooLargeError):
        safe_display("x" * 10, cap=5)


def test_projection_ready_then_terminal() -> None:
    ready = ConversationState.new("c1")
    view = project(ready)
    assert view.actions == ("submit",)
    assert view.focus == "input"

    terminal = replace(
        ready,
        last_safe_result=RecordedRunResult(
            status=RunStatus.COMPLETED, run_id="r", message="all done"
        ),
    )
    view = project(terminal)
    assert view.terminal_message == "all done"
    assert view.actions == ("submit",)


def test_projection_approval_and_recovery_forms() -> None:
    approval = _approval_state()
    assert project(approval).form_kind == "approval"
    assert project(approval).actions == ("approve", "reject")

    recovery = _recovery_state()
    assert project(recovery).form_kind == "recovery"
    assert project(recovery).actions == ("mark_succeeded", "mark_failed")


def test_projection_reopened_executing_is_unknown_effect_resume_only() -> None:
    """R19: 重开 RUNNABLE+EXECUTING checkpoint 时 effect 未知，只能 Resume，禁止 Cancel。"""
    started = accept_action(
        None,
        SubmitMessage(
            conversation_id="c1", action_seq=1, expected_revision=0, run_id="r3", message="hi"
        ),
    ).state
    batched = start_tool_batch(started, (ToolCall("call-3", "write_file", {}),))
    executing = mark_executing(
        batched, tool_call_id="call-3", intent_digest="d3", idempotency_key="k3"
    )
    view = project(executing)
    assert "interrupted unknown effect" in view.main_text
    assert view.actions == ("resume",)
    assert view.focus == "resume"


def test_run_status_label_is_stable() -> None:
    assert run_status_label(RunStatus.COMPLETED) == "completed"
    assert run_status_label(RunStatus.CONFLICT) == "conflict; reload"
