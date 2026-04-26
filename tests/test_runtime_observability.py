"""Runtime 可观测性回归测试。

这些测试只钉住日志事件，不改变 Runtime 行为预期。目标是以后遇到
“模型说要继续但没交付”的问题时，可以从 agent_log.jsonl 直接看到
stop_reason、当前 step、是否调用 mark_step_complete/no_progress 等关键信息。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from tests.conftest import FakeResponse, FakeTextBlock


def _read_jsonl(path):
    """读取测试专用 JSONL 日志。"""

    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _extract_text(content_blocks) -> str:
    """提取 fake response 里的文本块。"""

    return "\n".join(
        block.text
        for block in content_blocks
        if getattr(block, "type", None) == "text"
    ).strip()


def _running_report_state():
    """构造一个正在执行 report step 的最小 state。"""

    from agent.state import create_agent_state

    state = create_agent_state(system_prompt="test")
    state.task.status = "running"
    state.task.current_step_index = 0
    state.task.current_plan = {
        "goal": "生成旅行方案",
        "steps": [
            {
                "step_id": "step-1",
                "title": "输出详细方案",
                "description": "输出完整旅行方案",
                "step_type": "report",
                "suggested_tool": None,
                "expected_outcome": "完整方案",
                "completion_criteria": "已经输出完整方案",
            }
        ],
        "needs_confirmation": True,
    }
    return state


def test_end_turn_without_mark_step_complete_is_logged(monkeypatch, tmp_path):
    """模型 end_turn 但未调用 mark_step_complete 时，应记录当前 step 和完成信号缺失。"""

    import agent.logger as logger
    import agent.response_handlers as handlers

    monkeypatch.setattr(logger, "LOG_FILE", tmp_path / "agent_log.jsonl")
    monkeypatch.setattr(handlers, "save_checkpoint", lambda _state: None)

    state = _running_report_state()
    response = FakeResponse(
        content=[FakeTextBlock("我现在开始为你输出完整的详细旅游方案：")],
        stop_reason="end_turn",
    )

    result = handlers.handle_end_turn_response(
        response,
        state=state,
        turn_state=SimpleNamespace(),
        messages=state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert result is None
    entries = _read_jsonl(logger.LOG_FILE)
    observer_entries = [
        entry["data"]
        for entry in entries
        if entry["event"] == "runtime_observer"
    ]
    assert any(
        data["event_type"] == "model.end_turn"
        and data["payload"]["stop_reason"] == "end_turn"
        and data["payload"]["current_step_index"] == 0
        and data["payload"]["current_step_title"] == "输出详细方案"
        and data["payload"]["called_mark_step_complete"] is False
        for data in observer_entries
    )
    assert any(
        data["event_type"] == "runtime.end_turn_without_completion"
        for data in observer_entries
    )


def test_model_text_summary_is_truncated_in_observer_log(monkeypatch, tmp_path):
    """长 assistant 文本只记录长度和短 preview，不把全文打进日志。"""

    import agent.logger as logger
    import agent.response_handlers as handlers

    monkeypatch.setattr(logger, "LOG_FILE", tmp_path / "agent_log.jsonl")
    monkeypatch.setattr(handlers, "save_checkpoint", lambda _state: None)

    state = _running_report_state()
    long_text = "详细方案" * 100
    response = FakeResponse(
        content=[FakeTextBlock(long_text)],
        stop_reason="end_turn",
    )

    handlers.handle_end_turn_response(
        response,
        state=state,
        turn_state=SimpleNamespace(),
        messages=state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    raw_log = logger.LOG_FILE.read_text(encoding="utf-8")
    assert long_text not in raw_log

    entries = _read_jsonl(logger.LOG_FILE)
    model_end_turn = [
        entry["data"]
        for entry in entries
        if entry["event"] == "runtime_observer"
        and entry["data"]["event_type"] == "model.end_turn"
    ][-1]
    payload = model_end_turn["payload"]
    assert payload["text_length"] == len(long_text)
    assert len(payload["text_preview"]) < len(long_text)


def test_no_progress_detection_is_logged(monkeypatch, tmp_path):
    """连续 end_turn 无完成信号触发 no_progress 时，应留下明确日志。"""

    import agent.logger as logger
    import agent.response_handlers as handlers

    monkeypatch.setattr(logger, "LOG_FILE", tmp_path / "agent_log.jsonl")
    monkeypatch.setattr(handlers, "save_checkpoint", lambda _state: None)

    state = _running_report_state()
    state.task.consecutive_end_turn_without_progress = 1
    response = FakeResponse(
        content=[FakeTextBlock("我会继续处理。")],
        stop_reason="end_turn",
    )

    result = handlers.handle_end_turn_response(
        response,
        state=state,
        turn_state=SimpleNamespace(),
        messages=state.conversation.messages,
        extract_text_fn=_extract_text,
    )

    assert result == ""
    assert state.task.status == "awaiting_user_input"

    entries = _read_jsonl(logger.LOG_FILE)
    observer_entries = [
        entry["data"]
        for entry in entries
        if entry["event"] == "runtime_observer"
    ]
    assert any(
        data["event_type"] == "runtime.no_progress_detected"
        and data["payload"]["no_progress_reason"] == "runtime.no_progress"
        for data in observer_entries
    )


def test_checkpoint_save_records_short_runtime_fields(monkeypatch, tmp_path):
    """checkpoint 保存日志应包含 source、status、step 和 pending 信息。"""

    import agent.logger as logger
    from agent import checkpoint
    from agent.state import create_agent_state

    monkeypatch.setattr(logger, "LOG_FILE", tmp_path / "agent_log.jsonl")
    monkeypatch.setattr(checkpoint, "CHECKPOINT_PATH", tmp_path / "checkpoint.json")

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_step_index = 2
    state.task.pending_tool = {
        "tool_use_id": "toolu_1",
        "tool": "write_file",
        "input": {"path": "x.md"},
    }

    checkpoint.save_checkpoint(state, source="tests.runtime_observability")

    entries = _read_jsonl(logger.LOG_FILE)
    saved = [entry for entry in entries if entry["event"] == "checkpoint_saved"][-1]
    assert saved["data"] == {
        "checkpoint_source": "tests.runtime_observability",
        "task_status": "awaiting_tool_confirmation",
        "current_step_index": 2,
        "pending_user_input_kind": None,
        "pending_tool_name": "write_file",
    }
