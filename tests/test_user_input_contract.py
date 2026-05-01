"""UserInputEnvelope contract characterization tests。

本文件补齐 input boundary 的独立契约测试。v0.6.2 已经证明 paste burst /
multiline 是 TUI MVP 的最小实现目标：用户一次粘贴的多行编号列表必须作为
一个 user intent 被保留下来，而不是被 simple backend 拆成多轮，也不能在
input layer 被误判成菜单选择。

边界说明
--------
- `agent.user_input` 只描述输入事件/envelope，不修改 Runtime state、不保存
  checkpoint、不执行工具、不调用模型。
- 菜单/确认语义属于 input intent / confirmation handler / runtime 层；
  `1.` / `2.` 编号列表和单独 `1` 在 envelope 层都只是 raw text。
- 本轮仍不实现 Esc cancel 的 generation interruption，也不实现 user switch
  topic；这些需要 runtime lifecycle 设计，不能塞进 input contract 测试。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from types import SimpleNamespace

import pytest

from agent.confirm_handlers import ConfirmationContext, handle_feedback_intent_choice
from agent.input_intents import classify_confirmation_response, classify_user_input
from agent.input_resolution import (
    COLLECT_INPUT_ANSWER,
    RUNTIME_USER_INPUT_ANSWER,
    resolve_user_input,
)
from agent.state import create_agent_state
from agent.user_input import (
    UserInputEvent,
    build_user_input_envelope,
    cancelled_input_event,
    closed_input_event,
    submitted_input_event,
)


NUMBERED_PASTE = "\n".join(
    [
        "1. 北京出发",
        "2. 偏好高铁",
        "3. 高端酒店",
        "4. 先武汉后宜昌",
        "5. 自然风光和历史文化",
        "6. 预算 3500 元左右",
        "7. 单人出行",
        "8. 必须去黄鹤楼",
        "9. 出行日期：5 月 1 日到 5 月 3 日",
    ]
)


def test_numbered_multiline_paste_is_plain_multiline_input_contract() -> None:
    """编号列表粘贴在 input boundary 只是一段完整 multiline raw_text。

    这条测试保护 v0.6.2 TUI MVP 的核心语义：input layer 只保留用户一次提交
    的完整文本，不因为行首是 `1.` / `2.` 就把它当成菜单选择。后续 runtime
    可以按当前状态解释文本，但不能要求 backend 提前丢行、拆 turn 或塞选择字段。
    """

    envelope = build_user_input_envelope(NUMBERED_PASTE, source="cli")
    field_names = {field.name for field in fields(envelope)}

    assert envelope.raw_text == NUMBERED_PASTE
    assert envelope.normalized_text == NUMBERED_PASTE
    assert envelope.input_mode == "multiline"
    assert envelope.line_count == 9
    assert envelope.is_empty is False
    assert "selection" not in field_names
    assert "confirmation_response" not in field_names


def test_single_digit_input_stays_raw_text_until_confirmation_layer() -> None:
    """单独 `1` 在 envelope 层仍是普通 raw text，不是 backend 菜单决策。

    如果当前 Runtime 正处于确认状态，`classify_user_input` / confirm_handlers
    才能基于状态解释它；input backend 不能无上下文地把 `1` 当成 accept/reject。
    这避免 Ask User / Other free-text 被 backend 层绕过。
    """

    envelope = build_user_input_envelope("1", source="cli")

    assert envelope.raw_text == "1"
    assert envelope.normalized_text == "1"
    assert envelope.input_mode == "single_line"
    assert envelope.line_count == 1
    assert classify_confirmation_response(envelope.normalized_text) == "feedback"

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_plan_confirmation"
    intent = classify_user_input(envelope.raw_text, source="cli", state=state)

    assert intent.kind == "plan_confirmation"
    assert intent.metadata["confirmation_response"] == "feedback"


def test_user_input_envelope_is_frozen_input_boundary() -> None:
    """envelope 是输入快照，不能被 UI/display/runtime 后续随手 mutate。

    frozen dataclass 让 backend 收集到的 raw_text / line_count 成为稳定事实；
    后续如果 runtime 需要解释或转换，应该生成新的 decision/transition，而不是
    原地改 input event。
    """

    envelope = build_user_input_envelope("hello", source="cli")

    with pytest.raises(FrozenInstanceError):
        envelope.raw_text = "changed"  # type: ignore[misc]


def test_submitted_cancelled_closed_event_invariants() -> None:
    """submitted 必须携带 envelope；cancelled/closed 不能伪造成空文本提交。

    这条测试保护 Ask User / confirmation handler 边界：取消和关闭不是 free-text
    answer，也不应该进入 empty_user_input transition。Esc cancel 的完整 generation
    interruption 语义不在本轮实现，仍应由未来 runtime lifecycle 设计处理。
    """

    envelope = build_user_input_envelope("answer", source="tui")

    submitted = submitted_input_event(envelope, source="tui", channel="text_area_submit")
    cancelled = cancelled_input_event(source="tui", channel="escape_key")
    closed = closed_input_event(source="tui", channel="dialog_closed")

    assert submitted.event_type == "input.submitted"
    assert submitted.envelope is envelope
    assert cancelled.event_type == "input.cancelled"
    assert cancelled.envelope is None
    assert closed.event_type == "input.closed"
    assert closed.envelope is None

    with pytest.raises(ValueError, match="must carry"):
        UserInputEvent(
            event_type="input.submitted",
            event_source="tui",
            event_channel="text_area_submit",
        )

    with pytest.raises(ValueError, match="must not carry"):
        UserInputEvent(
            event_type="input.cancelled",
            event_source="tui",
            event_channel="escape_key",
            envelope=envelope,
        )


def test_pending_request_context_treats_natural_language_as_pending_answer() -> None:
    """pending_user_input_request 存在时，自然语言是在回答当前等待点。

    这条测试保护 User Input Resolution Contract 的最高优先级：同一句“预算
    3500，高铁优先”在普通 idle 状态可能是新任务，但在 awaiting_user_input
    且 pending 存在时必须解释为 pending answer。input layer / adapter 不能把它
    当成普通新任务，也不能提前推进 step。
    """

    state = create_agent_state(system_prompt="test")
    pending = {
        "awaiting_kind": "request_user_input",
        "question": "预算是多少？",
        "why_needed": "用于制定方案",
        "options": [],
        "context": "",
    }
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = pending

    intent = classify_user_input("预算 3500，高铁优先", source="cli", state=state)
    resolution = resolve_user_input(state, intent.raw_text)

    assert intent.kind == "request_user_reply"
    assert intent.metadata["awaiting_kind"] == "request_user_input"
    assert resolution.kind == RUNTIME_USER_INPUT_ANSWER
    assert resolution.pending_user_input_request == pending
    assert resolution.should_advance_step is False


def test_no_pending_context_treats_natural_language_as_normal_message() -> None:
    """没有 pending/confirmation context 时，自然语言就是普通用户输入。

    本轮不是做 topic switch 或新 HITL 系统；这里钉住的是反面契约：没有 runtime
    等待点时，adapter 不能因为文本像“补充信息”就把它塞进 request_user_input
    或 confirmation 路径。
    """

    state = create_agent_state(system_prompt="test")
    state.task.status = "idle"
    state.task.pending_user_input_request = None

    intent = classify_user_input("预算 3500，高铁优先", source="cli", state=state)

    assert intent.kind == "normal_message"
    assert intent.raw_text == "预算 3500，高铁优先"
    assert intent.metadata == {}


def test_awaiting_user_input_without_pending_is_collect_input_answer() -> None:
    """awaiting_user_input 没有 pending 时，是 collect_input/clarify 的回答。

    同一个 status 下有两种 Input 子语义：pending 存在表示执行期求助；pending
    不存在表示计划里的信息收集步骤。这个测试防止后续把二者都当成同一种
    HITL 输入，导致错误清 pending 或错误推进 step。
    """

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_user_input"
    state.task.pending_user_input_request = None

    intent = classify_user_input("酒店选高端，预算 3500", source="cli", state=state)
    resolution = resolve_user_input(state, intent.raw_text)

    assert intent.kind == "request_user_reply"
    assert intent.metadata["awaiting_kind"] == "collect_input"
    assert resolution.kind == COLLECT_INPUT_ANSWER
    assert resolution.pending_user_input_request is None
    assert resolution.should_advance_step is True


@pytest.mark.parametrize(
    ("status", "pending_attr", "expected_kind"),
    [
        ("awaiting_plan_confirmation", None, "plan_confirmation"),
        ("awaiting_step_confirmation", None, "step_confirmation"),
        ("awaiting_tool_confirmation", "pending_tool", "tool_confirmation"),
    ],
)
def test_y_is_contextual_confirmation_not_global_approval(
    status: str,
    pending_attr: str | None,
    expected_kind: str,
) -> None:
    """`y` 只有在 confirmation context 里才是确认选择。

    这保护 Choice / Approval 与普通 Input 的边界：plan、step、tool confirmation
    都可以解释 `y`，但这个解释权来自当前 runtime context，不来自 backend 的
    全局菜单猜测。
    """

    state = create_agent_state(system_prompt="test")
    state.task.status = status
    if pending_attr == "pending_tool":
        state.task.pending_tool = {
            "tool": "read_file",
            "tool_use_id": "toolu_test",
            "input": {"path": "README.md"},
        }

    intent = classify_user_input("y", source="cli", state=state)
    idle_intent = classify_user_input("y", source="cli", state=None)

    assert intent.kind == expected_kind
    assert intent.metadata["confirmation_response"] == "accept"
    assert idle_intent.kind == "normal_message"


def test_plan_confirmation_free_text_is_feedback_context_not_new_task() -> None:
    """plan confirmation 下的自由文本是修改/反馈，不是普通新任务。

    这条测试固定 Feedback/Input 边界：用户在计划确认阶段输入自然语言时，
    当前语义是“对现有计划的反馈”，后续是否进入三选一或重规划由
    confirmation handler 决定；input classifier 不能把它直接当新任务。
    """

    state = create_agent_state(system_prompt="test")
    state.task.status = "awaiting_plan_confirmation"

    intent = classify_user_input("请把酒店改成高端，并减少步行", source="cli", state=state)

    assert intent.kind == "plan_confirmation"
    assert intent.metadata["confirmation_response"] == "feedback"


def test_feedback_intent_invalid_option_keeps_pending_and_reasks() -> None:
    """awaiting_feedback_intent 下无效 option 不能误清 pending。

    用户输入 `4` 或自然语言时，系统不能猜它是 Other/free-text、新任务或取消。
    现有契约是：保持 status/pending/messages 不变，只重新发出选择提示。这属于
    User Input Resolution Contract，不是新增 HITL 子系统。
    """

    state = create_agent_state(system_prompt="test")
    pending = {
        "awaiting_kind": "feedback_intent",
        "question": "你想如何处理这段反馈？",
        "why_needed": "需要明确归属",
        "options": ["作为反馈", "作为新任务", "取消"],
        "context": "",
        "tool_use_id": "",
        "step_index": 0,
        "pending_feedback_text": "请改成三天两晚",
        "origin_status": "awaiting_plan_confirmation",
    }
    state.task.status = "awaiting_feedback_intent"
    state.task.pending_user_input_request = pending
    state.conversation.messages = [{"role": "user", "content": "原始任务"}]
    emitted: list[object] = []
    ctx = ConfirmationContext(
        state=state,
        turn_state=SimpleNamespace(on_runtime_event=emitted.append),
        client=object(),
        model_name="test-model",
        continue_fn=lambda _turn_state: "continued",
        start_planning_fn=lambda _text, _turn_state: "planned",
    )

    result = handle_feedback_intent_choice("4", ctx)

    assert result == ""
    assert state.task.status == "awaiting_feedback_intent"
    assert state.task.pending_user_input_request == pending
    assert state.conversation.messages == [{"role": "user", "content": "原始任务"}]
    assert len(emitted) == 1
