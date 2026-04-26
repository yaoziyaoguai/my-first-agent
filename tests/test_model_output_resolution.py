"""ModelOutputResolution 的只读事件解析测试。

这些测试保护的是“模型输出 -> RuntimeEvent”的映射关系，而不是工具执行或状态
转移。resolver 不接收 state，是为了让模型输出解析层保持只读边界：它只能判断
事件类型，不能顺手修改 task、messages 或 checkpoint。
"""

from __future__ import annotations

from inspect import signature

from tests.conftest import FakeToolUseBlock


def test_request_user_input_resolves_to_model_requested_user_input():
    from agent.model_output_resolution import (
        EVENT_MODEL_REQUESTED_USER_INPUT,
        resolve_tool_use_block,
    )

    block = FakeToolUseBlock(
        id="ru_1",
        name="request_user_input",
        input={
            "question": "预算是多少？",
            "why_needed": "用于制定计划",
            "options": ["3000", "5000"],
            "context": "旅行规划",
        },
    )

    event = resolve_tool_use_block(block)

    assert event.event_type == EVENT_MODEL_REQUESTED_USER_INPUT
    assert event.event_source == "model"
    assert event.event_payload["tool_use_id"] == "ru_1"
    assert event.event_payload["question"] == "预算是多少？"
    assert event.event_payload["why_needed"] == "用于制定计划"
    assert event.event_payload["options"] == ["3000", "5000"]
    assert event.event_payload["context"] == "旅行规划"


def test_mark_step_complete_resolves_to_model_completed_step():
    from agent.model_output_resolution import (
        EVENT_MODEL_COMPLETED_STEP,
        resolve_tool_use_block,
    )

    block = FakeToolUseBlock(
        id="meta_1",
        name="mark_step_complete",
        input={
            "completion_score": 90,
            "summary": "已完成",
            "outstanding": "无",
        },
    )

    event = resolve_tool_use_block(block)

    assert event.event_type == EVENT_MODEL_COMPLETED_STEP
    assert event.event_payload["tool_use_id"] == "meta_1"
    assert event.event_payload["completion_score"] == 90
    assert event.event_payload["summary"] == "已完成"
    assert event.event_payload["outstanding"] == "无"


def test_business_tool_resolves_to_model_used_business_tool():
    from agent.model_output_resolution import (
        EVENT_MODEL_USED_BUSINESS_TOOL,
        resolve_tool_use_block,
    )

    block = FakeToolUseBlock(
        id="tool_1",
        name="read_file",
        input={"path": "README.md"},
    )

    event = resolve_tool_use_block(block)

    assert event.event_type == EVENT_MODEL_USED_BUSINESS_TOOL
    assert event.event_payload["tool_use_id"] == "tool_1"
    assert event.event_payload["tool_name"] == "read_file"
    assert event.event_payload["tool_input"] == {"path": "README.md"}


def test_blocking_text_question_resolves_to_model_text_requested_user_input():
    from agent.model_output_resolution import (
        EVENT_MODEL_TEXT_REQUESTED_USER_INPUT,
        resolve_end_turn_output,
    )

    event = resolve_end_turn_output("请补充你的预算是多少？", no_progress_count=1)

    assert event is not None
    assert event.event_type == EVENT_MODEL_TEXT_REQUESTED_USER_INPUT
    assert event.event_source == "model"
    assert event.event_payload["text"] == "请补充你的预算是多少？"


def test_non_blocking_followups_do_not_resolve_to_text_requested_user_input():
    """最终答案后的开放式 follow-up 不是阻塞请求，不能让 runtime 进入等待态。"""
    from agent.model_output_resolution import resolve_end_turn_output

    for text in (
        "如需调整任何细节，请告诉我",
        "如果你想，我可以继续优化",
        "需要我进一步调整吗",
        "如需我帮你修改方案，可以继续告诉我",
    ):
        assert resolve_end_turn_output(text, no_progress_count=1) is None


def test_full_answer_with_followup_does_not_trigger_text_fallback():
    """已有完整结果时，结尾客套追问不能覆盖前面的完成态语义。"""
    from agent.model_output_resolution import resolve_end_turn_output

    text = (
        "第一天：抵达武汉，游览黄鹤楼和长江大桥。\n"
        "第二天：高铁前往宜昌，参观三峡大坝。\n"
        "第三天：游览清江画廊后返程。\n\n"
        "如需调整任何细节，请告诉我。"
    )

    assert resolve_end_turn_output(text, no_progress_count=1) is None


def test_blocking_text_requests_still_trigger_text_fallback():
    """协议外兜底仍保留：只有缺信息导致无法继续时才暂停等用户。"""
    from agent.model_output_resolution import (
        EVENT_MODEL_TEXT_REQUESTED_USER_INPUT,
        resolve_end_turn_output,
    )

    for text in (
        "为了继续执行，请提供预算范围",
        "缺少必要信息：出行日期，请补充",
        "我需要知道你的出发日期才能继续",
        "无法继续，除非你提供出发城市",
    ):
        event = resolve_end_turn_output(text, no_progress_count=1)
        assert event is not None
        assert event.event_type == EVENT_MODEL_TEXT_REQUESTED_USER_INPUT


def test_no_progress_count_resolves_to_runtime_no_progress():
    from agent.model_output_resolution import (
        EVENT_RUNTIME_NO_PROGRESS,
        resolve_end_turn_output,
    )

    event = resolve_end_turn_output("我还在思考", no_progress_count=2)

    assert event is not None
    assert event.event_type == EVENT_RUNTIME_NO_PROGRESS
    assert event.event_source == "runtime"
    assert event.event_payload["text"] == "我还在思考"
    assert event.event_payload["no_progress_count"] == 2


def test_max_tokens_resolves_to_model_hit_max_tokens():
    from agent.model_output_resolution import (
        EVENT_MODEL_HIT_MAX_TOKENS,
        resolve_max_tokens_output,
    )

    event = resolve_max_tokens_output()

    assert event.event_type == EVENT_MODEL_HIT_MAX_TOKENS
    assert event.event_source == "model"
    assert event.event_payload == {}


def test_resolvers_do_not_accept_state_parameter():
    """resolver 没有 state 参数，能防止解析层悄悄承担 transition/action 职责。"""
    from agent.model_output_resolution import (
        resolve_end_turn_output,
        resolve_max_tokens_output,
        resolve_tool_use_block,
    )

    assert "state" not in signature(resolve_tool_use_block).parameters
    assert "state" not in signature(resolve_end_turn_output).parameters
    assert "state" not in signature(resolve_max_tokens_output).parameters
