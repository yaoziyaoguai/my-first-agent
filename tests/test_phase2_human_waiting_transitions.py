"""Phase 2 human-waiting handler transitions 的真实路径测试。"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
    )


def _extract_text(blocks) -> str:
    return "\n".join(
        getattr(block, "text", "")
        for block in blocks
        if getattr(block, "type", None) == "text"
    )


def _patch_handler_side_effects(monkeypatch):
    import agent.response_handlers as handlers

    calls = {"save": 0, "clear": 0, "logs": [], "evidence": []}
    monkeypatch.setattr(
        handlers,
        "save_checkpoint",
        lambda _state, source=None: calls.__setitem__("save", calls["save"] + 1),
    )
    monkeypatch.setattr(
        handlers,
        "clear_checkpoint",
        lambda: calls.__setitem__("clear", calls["clear"] + 1),
    )
    monkeypatch.setattr(
        handlers,
        "log_event",
        lambda *args, **kwargs: calls["logs"].append((args, kwargs)),
    )
    monkeypatch.setattr(
        handlers,
        "_record_runtime_evidence",
        lambda *args, **kwargs: calls["evidence"].append((args, kwargs)),
    )
    return calls


def test_w05_step_confirmation_denied_has_no_side_effects(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W05: non-running state 不能进入 step confirmation 或记录成功事件。"""
    import agent.response_handlers as handlers

    calls = _patch_handler_side_effects(monkeypatch)
    monkeypatch.setattr(handlers, "is_current_step_completed", lambda _state: True)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.confirm_each_step = True
    fresh_state.task.status = "awaiting_user_input"
    before_messages = deepcopy(fresh_state.conversation.messages)
    before_log = deepcopy(fresh_state.task.tool_execution_log)

    result = handlers._maybe_advance_step(fresh_state)

    assert "状态迁移失败" in result
    assert fresh_state.task.status == "awaiting_user_input"
    assert fresh_state.task.current_step_index == 0
    assert fresh_state.task.tool_execution_log == before_log
    assert fresh_state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0, "logs": [], "evidence": []}


def test_w05_step_confirmation_allowed_saves_once(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W05: running -> awaiting_step_confirmation 由 caller 保存一次。"""
    import agent.response_handlers as handlers

    calls = _patch_handler_side_effects(monkeypatch)
    monkeypatch.setattr(handlers, "is_current_step_completed", lambda _state: True)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.confirm_each_step = True
    fresh_state.task.status = "running"

    result = handlers._maybe_advance_step(fresh_state)

    assert "请确认" in result
    assert fresh_state.task.status == "awaiting_step_confirmation"
    assert fresh_state.task.current_step_index == 0
    assert calls["save"] == 1
    assert calls["clear"] == 0


def test_w06_collect_step_denied_before_observation_or_message_append(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W06: stale collect-input entry denied 时所有 handler 副作用为零。"""
    import agent.response_handlers as handlers

    calls = _patch_handler_side_effects(monkeypatch)
    plan = deepcopy(two_step_plan)
    plan["steps"][0]["step_type"] = "collect_input"
    fresh_state.task.current_plan = plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.status = "idle"
    fresh_state.task.consecutive_max_tokens = 4
    before_messages = deepcopy(fresh_state.conversation.messages)

    result = handlers.handle_end_turn_response(
        _text_response("请提供预算范围"),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert "状态迁移失败" in result
    assert fresh_state.task.status == "idle"
    assert fresh_state.task.pending_user_input_request is None
    assert fresh_state.task.consecutive_max_tokens == 4
    assert fresh_state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0, "logs": [], "evidence": []}


def test_w06_collect_step_allowed_appends_then_saves_once(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W06: collect-input end_turn 成功后 append assistant 并保存一次。"""
    import agent.response_handlers as handlers

    calls = _patch_handler_side_effects(monkeypatch)
    plan = deepcopy(two_step_plan)
    plan["steps"][0]["step_type"] = "collect_input"
    fresh_state.task.current_plan = plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.status = "running"

    result = handlers.handle_end_turn_response(
        _text_response("请提供预算范围"),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert "请补充" in result
    assert fresh_state.task.status == "awaiting_user_input"
    assert fresh_state.conversation.messages[-1]["role"] == "assistant"
    assert calls["save"] == 1
    assert calls["clear"] == 0


def test_w07_fallback_stale_apply_has_no_handler_side_effects(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W07: validate 后状态变旧时，apply denied 且不提交任何 handler 副作用。"""
    import agent.response_handlers as handlers
    from agent.transitions import validate_task_transition as real_validate

    calls = _patch_handler_side_effects(monkeypatch)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.status = "running"
    fresh_state.task.consecutive_end_turn_without_progress = 0
    before_messages = deepcopy(fresh_state.conversation.messages)

    def _validate_then_stale(state, request):
        preflight = real_validate(state, request)
        state.task.status = "idle"
        return preflight

    monkeypatch.setattr(handlers, "validate_task_transition", _validate_then_stale)

    result = handlers.handle_end_turn_response(
        _text_response("为了继续执行，请提供预算范围"),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert "状态迁移失败" in result
    assert fresh_state.task.status == "idle"
    assert fresh_state.task.pending_user_input_request is None
    assert fresh_state.task.consecutive_end_turn_without_progress == 0
    assert fresh_state.conversation.messages == before_messages
    assert calls == {"save": 0, "clear": 0, "logs": [], "evidence": []}


def test_w07_fallback_allowed_writes_pending_then_saves_once(
    fresh_state,
    two_step_plan,
    monkeypatch,
):
    """W07: blocking text 成功进入 awaiting_user_input 并保存一次。"""
    import agent.response_handlers as handlers

    calls = _patch_handler_side_effects(monkeypatch)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.current_step_index = 0
    fresh_state.task.status = "running"

    result = handlers.handle_end_turn_response(
        _text_response("为了继续执行，请提供预算范围"),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert result == ""
    assert fresh_state.task.status == "awaiting_user_input"
    assert fresh_state.task.pending_user_input_request["awaiting_kind"] == "fallback_question"
    assert calls["save"] == 1
    assert calls["clear"] == 0


def _request_user_input_block() -> SimpleNamespace:
    return SimpleNamespace(
        id="toolu_request_user_input_phase2",
        name="request_user_input",
        input={
            "question": "预算是多少？",
            "why_needed": "用于当前步骤",
            "options": ["3000", "5000"],
            "context": "旅行计划",
        },
    )


def _patch_request_user_input_meta_tool(monkeypatch, executor) -> None:
    monkeypatch.setattr(
        executor,
        "is_meta_tool",
        lambda tool_name: tool_name == "request_user_input",
    )


def test_w09_request_user_input_denied_has_no_executor_side_effects(
    fresh_state,
    monkeypatch,
):
    """W09: non-running executor denied 时 tool log/pending/messages/checkpoint 不变。"""
    import agent.tool_executor as executor

    calls = {"save": 0}
    _patch_request_user_input_meta_tool(monkeypatch, executor)
    monkeypatch.setattr(
        executor,
        "save_checkpoint",
        lambda _state: calls.__setitem__("save", calls["save"] + 1),
    )
    fresh_state.task.status = "done"
    fresh_state.task.current_step_index = 0
    fresh_state.task.tool_execution_log = {
        "old-mark": {
            "tool": "mark_step_complete",
            "step_index": 0,
            "input": {"completion_score": 95},
        }
    }
    before_log = deepcopy(fresh_state.task.tool_execution_log)
    before_messages = deepcopy(fresh_state.conversation.messages)

    result = executor.execute_single_tool(
        _request_user_input_block(),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        turn_context={},
        messages=fresh_state.conversation.messages,
    )

    assert result == executor.TRANSITION_DENIED
    assert fresh_state.task.status == "done"
    assert fresh_state.task.pending_user_input_request is None
    assert fresh_state.task.tool_execution_log == before_log
    assert fresh_state.conversation.messages == before_messages
    assert calls["save"] == 0


def test_w09_request_user_input_stale_apply_has_no_executor_side_effects(
    fresh_state,
    monkeypatch,
):
    """W09: validate 后状态变旧时 apply denied，仍不能提交 executor 副作用。"""
    import agent.tool_executor as executor
    from agent.transitions import validate_task_transition as real_validate

    calls = {"save": 0}
    _patch_request_user_input_meta_tool(monkeypatch, executor)
    monkeypatch.setattr(
        executor,
        "save_checkpoint",
        lambda _state: calls.__setitem__("save", calls["save"] + 1),
    )
    fresh_state.task.status = "running"
    fresh_state.task.current_step_index = 0
    fresh_state.task.tool_execution_log = {}
    before_messages = deepcopy(fresh_state.conversation.messages)

    def _validate_then_stale(state, request):
        preflight = real_validate(state, request)
        state.task.status = "idle"
        return preflight

    monkeypatch.setattr(executor, "validate_task_transition", _validate_then_stale)

    result = executor.execute_single_tool(
        _request_user_input_block(),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        turn_context={},
        messages=fresh_state.conversation.messages,
    )

    assert result == executor.TRANSITION_DENIED
    assert fresh_state.task.status == "idle"
    assert fresh_state.task.pending_user_input_request is None
    assert fresh_state.task.tool_execution_log == {}
    assert fresh_state.conversation.messages == before_messages
    assert calls["save"] == 0


def test_w09_request_user_input_allowed_commits_then_saves_once(
    fresh_state,
    monkeypatch,
):
    """W09: allowed 后写 meta log、清当前 step stale mark、set pending 并保存一次。"""
    import agent.tool_executor as executor

    calls = {"save": 0}
    _patch_request_user_input_meta_tool(monkeypatch, executor)
    monkeypatch.setattr(
        executor,
        "save_checkpoint",
        lambda _state: calls.__setitem__("save", calls["save"] + 1),
    )
    fresh_state.task.status = "running"
    fresh_state.task.current_step_index = 0
    fresh_state.task.tool_execution_log = {
        "current-mark": {
            "tool": "mark_step_complete",
            "step_index": 0,
            "input": {"completion_score": 95},
        },
        "previous-mark": {
            "tool": "mark_step_complete",
            "step_index": 1,
            "input": {"completion_score": 95},
        },
    }

    result = executor.execute_single_tool(
        _request_user_input_block(),
        state=fresh_state,
        turn_state=SimpleNamespace(),
        turn_context={},
        messages=fresh_state.conversation.messages,
    )

    assert result is None
    assert fresh_state.task.status == "awaiting_user_input"
    assert fresh_state.task.pending_user_input_request["awaiting_kind"] == "request_user_input"
    assert "current-mark" not in fresh_state.task.tool_execution_log
    assert "previous-mark" in fresh_state.task.tool_execution_log
    assert "toolu_request_user_input_phase2" in fresh_state.task.tool_execution_log
    assert calls["save"] == 1
