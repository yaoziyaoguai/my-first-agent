"""真实 CLI 冒烟问题的回归测试。

这个文件不是补 happy path，而是把“武汉 + 宜昌三天旅游规划”真实运行中暴露的
Runtime / Harness 风险钉住：
- CLI 输入层是否会把用户自然粘贴的多行内容拆成多轮；
- request_user_input 恢复后，完整多字段答复是否进入 step_input 和模型上下文；
- 普通文本 fallback 是否只处理阻塞性问题，而不误伤最终答案后的客套 follow-up；
- request_user_input 是否是硬暂停点，不能同一轮继续调用模型导致重复追问。

这些测试服务于真实 bug 定位。若测试 xfail，reason 必须说明当前缺口和修复后
如何转成普通测试；不能为了全绿降低断言强度。
"""

from __future__ import annotations

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    meta_complete_response,
)
from tests.test_complex_scenarios import _plan_response
from tests.test_main_input import _silent_writer
from tests.test_main_loop import _reset_core_module
from tests.test_meta_tool import _request_user_input_response


TRAVEL_DETAILS = (
    "北京出发\n"
    "偏好高铁\n"
    "高端酒店\n"
    "先武汉后宜昌\n"
    "自然风光和历史文化\n"
    "预算 3500 元左右\n"
    "单人出行\n"
    "必须去黄鹤楼\n"
    "出行日期：5 月 1 日到 5 月 3 日"
)

TRAVEL_KEYWORDS = (
    "北京出发",
    "高铁",
    "高端酒店",
    "先武汉后宜昌",
    "自然风光和历史文化",
    "3500",
    "单人",
    "黄鹤楼",
    "5 月 1 日",
    "5 月 3 日",
)


def _make_reader(lines: list[str]):
    """模拟 CLI input()：每次只返回一行，用来复现普通 input 的真实限制。"""
    queue = list(lines)

    def reader(_prompt: str = "") -> str:
        if not queue:
            raise EOFError("test reader exhausted")
        return queue.pop(0)

    return reader


def _all_text_from_messages(messages: list[dict]) -> str:
    """把 API messages 中所有文本块拼起来，便于断言 step_input 是否投影给模型。"""
    texts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    texts.append(str(block.get("text") or block.get("content") or ""))
    return "\n".join(texts)


def test_plain_cli_pasted_numbered_multiline_should_be_one_user_intent():
    """真实旅游 case 的产品体验回归：不能要求用户必须知道并使用 /multi。

    v0.6.2 MVP（XFAIL-3 解锁）说明
    -----------------------------
    本测试在 v0.5.x 之前是 strict xfail：``read_user_input`` 普通分支只
    调用 ``reader(prompt)`` 一次，paste burst 的 9 行被拆成 9 轮 user
    intent，触发 plan/confirmation 循环混乱。

    v0.6.2 在 ``agent/input_backends/simple.py`` 的 ``read_user_input_text``
    普通分支末尾加了 ``_drain_paste_burst_lines``：
      - fake reader（本测试场景）→ 用 try/EOFError 循环 drain，
        9 元素 queue 被一次 pull 完，``"\\n".join`` 拼回；
      - 真实交互（reader is builtins.input + tty）→ 用
        ``select.select`` 零超时探测 stdin，仅当 paste 缓冲已就绪才继续
        读，避免阻塞单行交互。

    本测试 NOT 通过削弱断言或包成 try/except 假装通过；assertion 完整
    保留。如果未来谁误把 drain 逻辑回滚或改成 substring hack，本测试
    会立即抓到。
    """
    from main import read_user_input

    pasted_lines = [
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

    result = read_user_input(
        reader=_make_reader(pasted_lines),
        writer=_silent_writer,
    )

    assert result == "\n".join(pasted_lines)


def test_request_user_input_travel_details_project_to_step_input_and_execution_messages(
    monkeypatch,
):
    """用户一次性补全旅行字段后，Runtime 必须把完整答复投影给下一轮模型。"""
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "收集旅行信息", "read"), ("s2", "生成攻略", "report")]),
            _request_user_input_response(
                question="请补充武汉和宜昌三天行程的关键偏好",
                why_needed="缺少这些信息会导致行程顺序、预算和景点安排不可靠",
                tool_id="ru_travel",
                text="我需要先确认旅行约束",
            ),
            meta_complete_response(
                score=90,
                text="已吸收完整旅行偏好",
                tool_id="meta_after_travel",
            ),
            # step1 完成后当前 runtime 会自动推进 step2 并继续 loop；补一条响应，
            # 避免测试因为 fake response 给短而失败。真正要断言的是 step2 请求前
            # 的 messages 已经带上完整 step_input。
            meta_complete_response(
                score=95,
                text="已生成旅行攻略",
                tool_id="meta_finish_travel",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("规划武汉 + 宜昌三天旅行")
    chat("y")
    assert state.task.status == "awaiting_user_input"
    assert len(fake.requests) == 1

    chat(TRAVEL_DETAILS)

    step_input_texts = _all_text_from_messages(state.conversation.messages)
    execution_text = _all_text_from_messages(fake.requests[1]["messages"])

    for text in (step_input_texts, execution_text):
        assert "上一轮系统向用户询问" in text
        assert "用户已经回答" in text
        assert "不要重复追问已经由用户回答过的内容" in text
        assert "缺少这些信息会导致行程顺序、预算和景点安排不可靠" in text
        for keyword in TRAVEL_KEYWORDS:
            assert keyword in text


def test_final_answer_followup_does_not_pause_for_user_input(fresh_state, two_step_plan, monkeypatch):
    """完整答案后的开放式 follow-up 是非阻塞收尾，不应切 awaiting_user_input。"""
    from agent import response_handlers
    from agent.model_output_resolution import resolve_end_turn_output
    from agent.response_handlers import handle_end_turn_response

    monkeypatch.setattr(response_handlers, "save_checkpoint", lambda _state, source=None: None)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "running"
    fresh_state.task.current_step_index = 0
    text = (
        "第 1 天：北京高铁到武汉，游览黄鹤楼和长江大桥。\n"
        "第 2 天：武汉高铁到宜昌，参观三峡大坝。\n"
        "第 3 天：宜昌自然风光和历史文化游览后返程。\n"
        "预算按 3500 元左右控制，适合单人高端酒店出行。\n\n"
        "如需调整任何细节，请告诉我。"
    )
    response = FakeResponse(content=[FakeTextBlock(text=text)], stop_reason="end_turn")

    event = resolve_end_turn_output(text, no_progress_count=1)
    result = handle_end_turn_response(
        response,
        state=fresh_state,
        turn_state=object(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=lambda blocks: "\n".join(getattr(block, "text", "") for block in blocks),
    )

    assert event is None
    assert result is None
    assert fresh_state.task.status == "running"
    assert fresh_state.task.pending_user_input_request is None


def test_blocking_text_fallback_pauses_for_user_input(fresh_state, two_step_plan, monkeypatch):
    """协议外文本兜底仍要保留：真正阻塞当前任务的信息请求必须暂停等用户。"""
    from agent import response_handlers
    from agent.model_output_resolution import EVENT_MODEL_TEXT_REQUESTED_USER_INPUT
    from agent.response_handlers import handle_end_turn_response

    monkeypatch.setattr(response_handlers, "save_checkpoint", lambda _state, source=None: None)
    fresh_state.task.current_plan = two_step_plan
    fresh_state.task.status = "running"
    fresh_state.task.current_step_index = 0
    text = "为了继续执行，请提供预算范围"
    response = FakeResponse(content=[FakeTextBlock(text=text)], stop_reason="end_turn")

    result = handle_end_turn_response(
        response,
        state=fresh_state,
        turn_state=object(),
        messages=fresh_state.conversation.messages,
        extract_text_fn=lambda blocks: "\n".join(getattr(block, "text", "") for block in blocks),
    )

    pending = fresh_state.task.pending_user_input_request
    assert result == ""
    assert fresh_state.task.status == "awaiting_user_input"
    assert pending is not None
    assert pending["awaiting_kind"] == "fallback_question"
    assert pending["question"] == text
    assert pending["why_needed"]
    assert response_handlers.resolve_end_turn_output(
        text,
        fresh_state.task.consecutive_end_turn_without_progress,
    ).event_type == EVENT_MODEL_TEXT_REQUESTED_USER_INPUT


def test_request_user_input_is_hard_stop_even_when_model_has_more_responses(monkeypatch):
    """request_user_input 是 Runtime interrupt；触发后本轮 loop 必须停住，不能重复追问。"""
    fake = FakeAnthropicClient(
        responses=[
            _plan_response([("s1", "收集旅行信息", "read"), ("s2", "生成攻略", "report")]),
            _request_user_input_response(
                question="请补充旅行偏好",
                why_needed="需要这些信息规划武汉宜昌行程",
                tool_id="ru_stop_1",
                text="先问用户",
            ),
            # 如果 loop 没有硬停，会错误消费这条响应并产生第二次 request_user_input。
            FakeResponse(
                content=[
                    FakeTextBlock(text="不应该被调用"),
                    FakeToolUseBlock(
                        id="ru_stop_2",
                        name="request_user_input",
                        input={
                            "question": "重复追问预算",
                            "why_needed": "这条不应该出现",
                            "options": [],
                            "context": "",
                        },
                    ),
                ],
                stop_reason="tool_use",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chat("规划武汉 + 宜昌三天旅行")
    chat("y")

    assert state.task.status == "awaiting_user_input"
    assert state.task.pending_user_input_request is not None
    assert state.task.pending_user_input_request["question"] == "请补充旅行偏好"
    assert len(fake.requests) == 1


# ============================================================
# B2 契约护栏：普通 CLI 输出不能裸 print 内部数据 / protocol dump
#
# 这两条测试守护 docs/CLI_OUTPUT_CONTRACT.md §5 禁止项。它们不是覆盖
# 新功能，而是把"v0.1 已修复的违反契约 print"钉死，避免任何回归。
# 任何把 DEBUG_PROTOCOL 改回 True 默认值，或重新引入裸 print(checkpoint)
# 的改动，都会被这两条测试拦下。
# ============================================================


def test_b2_resume_does_not_naked_print_checkpoint_dict(
    tmp_path, monkeypatch, capsys
):
    """B2 契约：try_resume_from_checkpoint 不能把整段 checkpoint dict 泄到 stdout。

    历史回归点：agent/session.py:42 曾有 `print("[DEBUG] checkpoint:", checkpoint)`，
    无 env guard 直接 print 整段 dict（含 conversation messages），是 v0.1 阶段
    "用户根本看不清 Agent 在做什么"的典型来源。B2 已修：仅在
    MY_FIRST_AGENT_DEBUG=1 时打印 checkpoint keys（不打 values），普通 CLI 永远
    不会泄会话历史。详见 docs/CLI_OUTPUT_CONTRACT.md §5、§6。
    """

    from agent import checkpoint as checkpoint_module
    from agent import session as session_module

    secret_marker = "SECRET_LEAK_CANARY_DO_NOT_PRINT"
    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(checkpoint_module, "CHECKPOINT_PATH", checkpoint_path)
    # 不让 MY_FIRST_AGENT_DEBUG 在测试环境意外开启。
    monkeypatch.delenv("MY_FIRST_AGENT_DEBUG", raising=False)

    import json as _json

    checkpoint_path.write_text(
        _json.dumps(
            {
                "task": {"user_goal": "测试任务", "current_step_index": 0},
                "conversation": {
                    "messages": [
                        {"role": "user", "content": secret_marker},
                        {"role": "assistant", "content": "回复"},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    # try_resume_from_checkpoint 会 input("要继续这个任务吗？(y/n): ")。
    # 我们回 "n" 让它走 clear 分支，避免触碰真实 core.state。
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")

    session_module.try_resume_from_checkpoint()

    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert secret_marker not in combined, (
        "B2 契约违反：checkpoint conversation messages 泄到了 stdout。"
        f" 输出片段：\n{combined[:500]}"
    )
    assert "[DEBUG] checkpoint:" not in combined, (
        "B2 契约违反：仍有裸 [DEBUG] checkpoint: 输出。详见"
        " docs/CLI_OUTPUT_CONTRACT.md §5。"
    )


def test_b2_chat_default_does_not_emit_protocol_dump(monkeypatch, capsys):
    """B2 契约：普通 CLI 默认不能出现 REQUEST/RESPONSE protocol dump。

    历史回归点：agent/core.py 的 DEBUG_PROTOCOL 历史默认 True，且
    _debug_print_request / _debug_print_response 会在每轮模型调用时 print 巨量
    REQUEST → Anthropic / RESPONSE ← Anthropic dump。当前调用点已注释，但只要
    任何人取消注释，污染就会立刻回归。B2 已修：DEBUG_PROTOCOL 默认 False，且
    函数体首部加 MY_FIRST_AGENT_PROTOCOL_DUMP env guard。
    详见 docs/CLI_OUTPUT_CONTRACT.md §4 / §5.2。
    """

    from agent import core as core_module

    # 1) 模块常量层面：默认必须是 False。
    assert core_module.DEBUG_PROTOCOL is False, (
        "B2 契约违反：core.DEBUG_PROTOCOL 默认必须为 False。"
    )

    # 2) 函数级 guard：即便 DEBUG_PROTOCOL=True，没设环境变量也不能输出。
    monkeypatch.delenv("MY_FIRST_AGENT_PROTOCOL_DUMP", raising=False)
    monkeypatch.setattr(core_module, "DEBUG_PROTOCOL", True)
    core_module._debug_print_request("sys", [], [])

    class _FakeResp:
        stop_reason = "end_turn"
        content = []
        usage = None

    core_module._debug_print_response(_FakeResp())

    captured = capsys.readouterr()
    combined = captured.out + captured.err

    forbidden_substrings = (
        "REQUEST → Anthropic",
        "RESPONSE ← Anthropic",
    )
    for marker in forbidden_substrings:
        assert marker not in combined, (
            f"B2 契约违反：未启用 MY_FIRST_AGENT_PROTOCOL_DUMP 时仍输出了"
            f" protocol dump 标记 {marker!r}。详见"
            " docs/CLI_OUTPUT_CONTRACT.md §5.2。"
        )
