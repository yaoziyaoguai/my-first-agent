"""planner / task_runtime / conversation_events 的行为测试。

覆盖几个小但关键的"语义规则"：
- planner 的 steps_estimate 判断分支
- is_current_step_completed 走 mark_step_complete 工具日志而非关键词
- advance_current_step_if_needed 的推进规则
- append_control_event 的事件类型生成
"""

from __future__ import annotations

from agent.conversation_events import (
    append_control_event,
    append_tool_result,
    has_tool_result,
)
from agent.plan_schema import Plan, PlanStep
from agent.task_runtime import (
    advance_current_step_if_needed,
    get_latest_step_completion,
    is_current_step_completed,
)
from config import STEP_COMPLETION_THRESHOLD


# ---------- is_current_step_completed ----------

class _FakeState:
    def __init__(self, plan_dict, step_index=0):
        self.task = type("T", (), {})()
        self.task.current_plan = plan_dict
        self.task.current_step_index = step_index
        self.task.status = "running"
        self.task.tool_execution_log = {}


def _record_meta(state, *, score, summary="done", outstanding="无", step_index=None, tool_use_id="meta1"):
    """在 fake state 里塞一条 mark_step_complete 日志。"""
    state.task.tool_execution_log[tool_use_id] = {
        "tool": "mark_step_complete",
        "input": {
            "completion_score": score,
            "summary": summary,
            "outstanding": outstanding,
        },
        "result": "",
        "status": "meta_recorded",
        "step_index": state.task.current_step_index if step_index is None else step_index,
    }


def _make_plan_dict():
    return Plan(
        goal="g",
        thinking="t",
        steps=[
            PlanStep(step_id="s1", title="一", description="d1", step_type="read"),
            PlanStep(step_id="s2", title="二", description="d2", step_type="report"),
        ],
    ).model_dump()


def test_is_current_step_completed_when_meta_score_meets_threshold():
    """log 里有当前步骤的 mark_step_complete 且分值 ≥ 阈值 → True。"""
    state = _FakeState(_make_plan_dict())
    _record_meta(state, score=STEP_COMPLETION_THRESHOLD)
    assert is_current_step_completed(state) is True


def test_is_current_step_completed_when_meta_score_below_threshold():
    """分值未达阈值 → False（系统会把 outstanding 注入下轮让模型继续）。"""
    state = _FakeState(_make_plan_dict())
    _record_meta(state, score=STEP_COMPLETION_THRESHOLD - 1)
    assert is_current_step_completed(state) is False


def test_is_current_step_completed_ignores_other_step_completions():
    """log 里只有别的步骤（step_index 不匹配）的完成项 → 当前步骤仍未完成。"""
    state = _FakeState(_make_plan_dict(), step_index=1)
    # step_index=0 是别的步骤
    _record_meta(state, score=100, step_index=0)
    assert is_current_step_completed(state) is False


def test_is_current_step_completed_returns_false_without_meta_call():
    """没调过 mark_step_complete 的步骤一律 False，不再吃关键词。"""
    state = _FakeState(_make_plan_dict())
    # log 里有别的工具记录，但没 mark_step_complete
    state.task.tool_execution_log["t1"] = {
        "tool": "run_shell",
        "input": {"cmd": "ls"},
        "result": "...",
        "status": "executed",
        "step_index": 0,
    }
    assert is_current_step_completed(state) is False


def test_is_current_step_completed_returns_false_when_no_plan():
    """没 plan 时无论 log 如何都应当返回 False。"""
    state = _FakeState(plan_dict=None)
    _record_meta(state, score=100)
    assert is_current_step_completed(state) is False


def test_get_latest_step_completion_returns_last_recorded_for_current_step():
    """同一步骤多次自评时，"最近一条"胜出（后来居上）。"""
    state = _FakeState(_make_plan_dict())
    _record_meta(state, score=40, summary="低分", outstanding="一堆", tool_use_id="m1")
    _record_meta(state, score=90, summary="补完了", outstanding="无", tool_use_id="m2")
    latest = get_latest_step_completion(state)
    assert latest == {"completion_score": 90, "summary": "补完了", "outstanding": "无"}


# ---------- advance_current_step_if_needed ----------

def test_advance_from_non_last_step_moves_to_next(monkeypatch):
    """第 1 步 → 第 2 步：step_index++，status=running。"""
    from agent import checkpoint
    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda s: None)

    state = _FakeState(_make_plan_dict(), step_index=0)
    advance_current_step_if_needed(state)
    assert state.task.current_step_index == 1
    assert state.task.status == "running"


def test_advance_from_last_step_marks_done(monkeypatch):
    """最后一步完成后 status=done。"""
    from agent import checkpoint
    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda s: None)

    state = _FakeState(_make_plan_dict(), step_index=1)
    advance_current_step_if_needed(state)
    assert state.task.status == "done"


def test_advance_without_plan_marks_done(monkeypatch):
    """没有 plan 时直接 done，不会 crash。"""
    from agent import checkpoint
    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda s: None)

    state = _FakeState(plan_dict=None)
    advance_current_step_if_needed(state)
    assert state.task.status == "done"


# ---------- conversation_events ----------

def test_append_control_event_writes_semantic_text():
    """plan_confirm_yes 应该产生'用户接受当前计划'这种语义文字，
    而不是把裸 'y' 塞进 messages。"""
    messages: list = []
    append_control_event(messages, "plan_confirm_yes", {})

    assert len(messages) == 1
    msg = messages[0]
    assert msg["role"] == "user"
    content = msg["content"]
    # content 是 list of blocks
    assert isinstance(content, list)
    text = content[0].get("text", "")
    assert "用户接受" in text and "y" != text.strip()


def test_append_control_event_includes_feedback_payload():
    """plan_feedback 事件应当把用户的反馈内容嵌进文本。"""
    messages: list = []
    append_control_event(messages, "plan_feedback", {"feedback": "加一个安全检查步骤"})

    content = messages[0]["content"]
    text = content[0]["text"]
    assert "加一个安全检查步骤" in text


def test_append_control_event_step_input_is_semantic():
    """step_input 事件应当明确记录用户补充信息。"""
    messages: list = []
    append_control_event(messages, "step_input", {"content": "旅游出行，舒适型"})

    content = messages[0]["content"]
    text = content[0]["text"]
    assert "【当前步骤用户补充信息】" in text
    assert "旅游出行，舒适型" in text


def test_step_input_with_question_renders_as_authoritative_context():
    """request_user_input/fallback 回复应渲染成权威的已收集上下文。"""
    messages: list = []
    user_reply = (
        "从北京出发\n"
        "优先高铁\n"
        "高端酒店\n"
        "先武汉后宜昌"
    )
    append_control_event(messages, "step_input", {
        "question": "请补充出行偏好？",
        "why_needed": "无偏好无法制定行程",
        "content": user_reply,
    })

    text = messages[0]["content"][0]["text"]
    assert "用户已经回答" in text
    assert "请补充出行偏好？" in text
    assert user_reply in text
    assert "不要重复追问已经由用户回答过的内容" in text
    assert "无偏好无法制定行程" in text


def test_append_tool_result_writes_user_message():
    """append_tool_result 应当追加一条 user 消息，content 是 tool_result 块。"""
    messages: list = []
    append_tool_result(messages, "T_abc", "执行结果")

    assert len(messages) == 1
    msg = messages[0]
    assert msg["role"] == "user"
    assert msg["content"][0]["type"] == "tool_result"
    assert msg["content"][0]["tool_use_id"] == "T_abc"
    assert msg["content"][0]["content"] == "执行结果"


def test_has_tool_result_finds_existing():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "T1", "content": "r"}
            ],
        }
    ]
    assert has_tool_result(messages, "T1") is True
    assert has_tool_result(messages, "T_OTHER") is False


def test_has_tool_result_handles_mixed_content():
    """messages 里混杂字符串 content 和 list content，不应该 crash。"""
    messages = [
        {"role": "user", "content": "字符串 content"},   # 没有 type=tool_result
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "仅 text"}],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "T_FOUND", "content": "ok"}
            ],
        },
    ]
    assert has_tool_result(messages, "T_FOUND") is True
    assert has_tool_result(messages, "T_MISSING") is False
