"""InputResolution 的架构语义测试。

这些测试不关心 handler 后续如何修改 state，只验证“用户输入先被解析成哪种
runtime 语义”。这能把输入分类规则从状态转移副作用里拆出来单独保护。
"""

from __future__ import annotations

from agent.input_resolution import (
    COLLECT_INPUT_ANSWER,
    EMPTY_USER_INPUT,
    RUNTIME_USER_INPUT_ANSWER,
    resolve_user_input,
)


def test_resolve_awaiting_user_input_without_pending_as_collect_answer(fresh_state):
    """没有 pending 表示这是 collect_input/clarify step 的回答，应推进 step。"""
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = None

    resolution = resolve_user_input(fresh_state, "用户补充的信息")

    assert resolution.kind == COLLECT_INPUT_ANSWER
    assert resolution.content == "用户补充的信息"
    assert resolution.pending_user_input_request is None
    assert resolution.should_advance_step is True


def test_resolve_awaiting_user_input_with_pending_as_runtime_answer(fresh_state):
    """有 pending 表示执行中途求助的回答，只补当前 step，不推进 step。"""
    pending = {
        "awaiting_kind": "request_user_input",
        "question": "预算是多少？",
        "why_needed": "用于制定方案",
    }
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = pending

    resolution = resolve_user_input(fresh_state, "预算 3500 元左右")

    assert resolution.kind == RUNTIME_USER_INPUT_ANSWER
    assert resolution.content == "预算 3500 元左右"
    assert resolution.pending_user_input_request == pending
    assert resolution.should_advance_step is False


def test_resolve_runtime_answer_without_awaiting_kind_keeps_legacy_compat(fresh_state):
    """旧 checkpoint 里的 pending 没有 awaiting_kind，仍应按 runtime 答复处理。"""
    pending = {
        "question": "预算是多少？",
        "why_needed": "用于制定方案",
    }
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = pending

    resolution = resolve_user_input(fresh_state, "预算 3500 元左右")

    assert resolution.kind == RUNTIME_USER_INPUT_ANSWER
    assert resolution.pending_user_input_request == pending
    assert resolution.should_advance_step is False


def test_resolve_user_input_preserves_multiline_content(fresh_state):
    """解析层必须保留用户原文，不能在进入 transition 前丢掉多行信息。"""
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = {
        "awaiting_kind": "request_user_input",
        "question": "请补充行程偏好",
        "why_needed": "用于规划行程",
    }
    user_input = (
        "北京出发\n"
        "高铁\n"
        "高端酒店\n"
        "先武汉后宜昌\n"
        "自然风光和历史文化\n"
        "3500 元左右\n"
        "单人出行\n"
        "黄鹤楼"
    )

    resolution = resolve_user_input(fresh_state, user_input)

    assert resolution.content == user_input


def test_empty_input_resolves_to_empty_for_collect_input_path(fresh_state):
    """空输入是 User Input Layer 前的防御事件，不能被当作 collect_input 答案。"""
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = None

    resolution = resolve_user_input(fresh_state, "")

    assert resolution.kind == EMPTY_USER_INPUT
    assert resolution.content == ""
    assert resolution.pending_user_input_request is None
    assert resolution.should_advance_step is False


def test_blank_input_resolves_to_empty_for_runtime_pending_path(fresh_state):
    """pending 存在时空白输入也不是有效回答，尤其不能清掉旧 pending。"""
    pending = {
        "awaiting_kind": "request_user_input",
        "question": "预算是多少？",
        "why_needed": "用于制定方案",
    }
    fresh_state.task.status = "awaiting_user_input"
    fresh_state.task.pending_user_input_request = pending

    resolution = resolve_user_input(fresh_state, "   ")

    assert resolution.kind == EMPTY_USER_INPUT
    assert resolution.content == "   "
    assert resolution.pending_user_input_request == pending
    assert resolution.should_advance_step is False
