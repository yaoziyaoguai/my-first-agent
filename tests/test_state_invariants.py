"""state.py 的不变量单测。

回归防护：reset_task 漏字段是我们本周踩过的一个实际坑。
如果以后有人给 TaskState 加新字段但忘了在 reset_task 里清，这些测试会红。
"""

from __future__ import annotations

from dataclasses import fields

from agent.state import TaskState, create_agent_state


# 下面这组字段是已知"用户会话结束应该归零"的字段。
# 如果你给 TaskState 加了新字段又应该跨任务清零，请把它加进这个列表；
# 加进来后对应的 reset_task 也要清掉，否则测试会提醒你。
RESETTABLE_FIELDS = {
    "user_goal",
    "current_plan",
    "status",
    "retry_count",
    "current_step_index",
    "loop_iterations",
    "consecutive_rejections",
    "consecutive_max_tokens",
    "consecutive_end_turn_without_progress",
    "tool_call_count",
    "last_error",
    "effective_review_request",
    "pending_tool",
    "pending_user_input_request",
    "confirm_each_step",
    "tool_execution_log",
}


def _set_dirty(state) -> None:
    """把 task 所有字段都改成"脏"的值，方便验证 reset 是否确实清掉了。"""
    state.task.user_goal = "某个目标"
    state.task.current_plan = {"goal": "some", "steps": []}
    state.task.status = "running"
    state.task.retry_count = 5
    state.task.current_step_index = 3
    state.task.loop_iterations = 42
    state.task.consecutive_rejections = 7
    state.task.consecutive_max_tokens = 2
    state.task.consecutive_end_turn_without_progress = 3
    state.task.tool_call_count = 11
    state.task.last_error = "some error"
    state.task.effective_review_request = True
    state.task.pending_tool = {"tool_use_id": "X", "tool": "Y", "input": {}}
    state.task.pending_user_input_request = {
        "question": "?", "why_needed": "?", "options": [], "context": "",
        "tool_use_id": "ru_X", "step_index": 0,
    }
    state.task.confirm_each_step = True
    state.task.tool_execution_log = {"toolu_1": {"tool": "x", "input": {}, "result": "r"}}


def test_reset_task_clears_all_resettable_fields():
    """reset_task 必须把 RESETTABLE_FIELDS 里所有字段清到默认值。

    特别关注 pending_tool / tool_execution_log / tool_call_count——
    这三个字段本周之前 reset_task 是漏清的，会造成跨任务状态残留。
    """
    state = create_agent_state(system_prompt="test")
    _set_dirty(state)

    state.reset_task()

    assert state.task.user_goal is None
    assert state.task.current_plan is None
    assert state.task.status == "idle"
    assert state.task.retry_count == 0
    assert state.task.current_step_index == 0
    assert state.task.loop_iterations == 0
    assert state.task.consecutive_rejections == 0
    assert state.task.consecutive_max_tokens == 0
    assert state.task.consecutive_end_turn_without_progress == 0
    assert state.task.tool_call_count == 0
    assert state.task.last_error is None
    assert state.task.effective_review_request is False
    assert state.task.pending_tool is None
    assert state.task.pending_user_input_request is None
    assert state.task.confirm_each_step is False
    assert state.task.tool_execution_log == {}


def test_resettable_fields_covers_all_task_fields():
    """保险杠测试：如果有人给 TaskState 加了新字段但没加进 RESETTABLE_FIELDS，
    这个测试会红，提醒他考虑"任务结束时这个字段应不应该清"。
    """
    actual = {f.name for f in fields(TaskState)}
    missing = actual - RESETTABLE_FIELDS
    assert not missing, (
        f"TaskState 有新字段 {missing} 没被纳入 RESETTABLE_FIELDS。\n"
        "请判断：\n"
        "  1) 这个字段应该在 reset_task 里清 → 加进 RESETTABLE_FIELDS 和 reset_task\n"
        "  2) 这个字段应该跨任务保留 → 在 RESETTABLE_FIELDS 之外再维护一个 allowlist"
    )
