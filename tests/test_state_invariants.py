"""state.py 的不变量单测。

回归防护：reset_task 漏字段是我们本周踩过的一个实际坑。
如果以后有人给 TaskState 加新字段但忘了在 reset_task 里清，这些测试会红。
"""

from __future__ import annotations

from dataclasses import fields

from agent.state import (
    TaskState,
    create_agent_state,
    is_known_task_status,
    is_terminal_task_status,
    task_status_requires_plan,
)


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


def test_task_status_requires_plan_for_plan_and_step_confirmation():
    """plan / step 确认态是计划子状态，没有 current_plan 就无法恢复 UI。"""
    assert task_status_requires_plan(TaskState(status="awaiting_plan_confirmation"))
    assert task_status_requires_plan(TaskState(status="awaiting_step_confirmation"))


def test_task_status_requires_plan_for_collect_input_but_not_runtime_pending():
    """awaiting_user_input 内部有两类语义：collect_input 需要 plan，runtime pending 不强制。"""
    collect_input_task = TaskState(
        status="awaiting_user_input",
        pending_user_input_request=None,
    )
    runtime_pending_task = TaskState(
        status="awaiting_user_input",
        pending_user_input_request={
            "awaiting_kind": "request_user_input",
            "question": "预算是多少？",
        },
    )

    assert task_status_requires_plan(collect_input_task)
    assert not task_status_requires_plan(runtime_pending_task)


def test_task_status_requires_plan_keeps_tool_confirmation_and_terminal_states_free():
    """工具确认由 pending_tool 表达；terminal / idle 状态也不应因 plan=None 被重置。"""
    assert not task_status_requires_plan(TaskState(status="awaiting_tool_confirmation"))
    assert not task_status_requires_plan(TaskState(status="idle"))
    assert not task_status_requires_plan(TaskState(status="done"))
    assert not task_status_requires_plan(TaskState(status="failed"))
    assert not task_status_requires_plan(TaskState(status="cancelled"))


def test_task_status_requires_plan_keeps_legacy_running_behavior():
    """running 当前仍混合了 plan step 执行和生命周期语义，第一阶段保持旧 reset 行为。"""
    assert task_status_requires_plan(TaskState(status="running"))


def test_unknown_task_status_is_treated_as_inconsistent_without_plan():
    """未知 status 多半来自损坏 checkpoint 或未来版本，plan=None 时让 core 自愈。"""
    task = TaskState(status="mystery_status")

    assert not is_known_task_status(task.status)
    assert task_status_requires_plan(task)


def test_terminal_task_status_helper():
    """terminal helper 集中表达未来 done / failed / cancelled 的同类语义。"""
    assert is_terminal_task_status("done")
    assert is_terminal_task_status("failed")
    assert is_terminal_task_status("cancelled")
    assert not is_terminal_task_status("running")


def test_core_resets_requires_plan_status_when_plan_missing(monkeypatch, capsys):
    """core invariant 应通过 helper 识别“必须有 plan”的损坏态并 reset。"""
    from tests.conftest import FakeAnthropicClient, text_response
    from tests.test_main_loop import _planner_no_plan_response, _reset_core_module

    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            text_response("收到"),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)
    state.task.status = "awaiting_user_input"
    state.task.current_plan = None
    state.task.pending_user_input_request = None

    from agent.core import chat

    chat("继续")

    out = capsys.readouterr().out
    assert "检测到不一致状态" in out


def test_core_does_not_reset_tool_confirmation_without_plan(monkeypatch):
    """awaiting_tool_confirmation + pending_tool 可来自单步无 plan 任务，不应被 plan invariant reset。"""
    from tests.conftest import FakeAnthropicClient
    from tests.test_main_loop import _reset_core_module

    fake = FakeAnthropicClient(responses=[])
    state = _reset_core_module(monkeypatch, fake)
    state.task.status = "awaiting_tool_confirmation"
    state.task.current_plan = None
    state.task.pending_tool = {"tool_use_id": "T1", "tool": "w", "input": {}}

    import agent.core as core

    monkeypatch.setattr(
        core,
        "handle_tool_confirmation",
        lambda _user_input, _ctx: "tool handled",
    )

    assert core.chat("n") == "tool handled"
    assert state.task.pending_tool is not None


def test_core_does_not_reset_runtime_user_input_pending_without_plan(monkeypatch):
    """runtime pending 自带恢复问题；没有 plan 时也不应被 current_plan invariant 误伤。"""
    from tests.conftest import FakeAnthropicClient
    from tests.test_main_loop import _reset_core_module

    fake = FakeAnthropicClient(responses=[])
    state = _reset_core_module(monkeypatch, fake)
    state.task.status = "awaiting_user_input"
    state.task.current_plan = None
    state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "预算是多少？",
        "why_needed": "用于继续当前任务",
    }

    import agent.core as core

    monkeypatch.setattr(
        core,
        "handle_user_input_step",
        lambda _user_input, _ctx: "input handled",
    )

    assert core.chat("3500") == "input handled"
    assert state.task.pending_user_input_request is not None
