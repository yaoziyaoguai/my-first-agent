"""主循环集成测试。

用 FakeAnthropicClient 驱动 agent.core.chat()，覆盖几条关键路径：
- 规划跳过（单步任务）+ 一次 tool_use 循环 + end_turn 收束
- 模型反复返回同一个 tool_use 是否会被限流兜底
- 多 tool_use 并行，其中一个需要确认：剩余块是否被补占位 tool_result

这些测试直接命中上周咱们现场翻车过的两个问题域——
不会因为看不到 API 请求体而漏过 bug。
"""

from __future__ import annotations

import json
from types import SimpleNamespace


from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    text_response,
    tool_use_response,
)


# ---------- helpers ----------

def _reset_core_module(monkeypatch, fake_client):
    """把 core 模块的全局 client / state 换成测试专用的，test 结束自动回滚。

    注意：core 是模块级全局 state。测试之间必须互相隔离，否则 state.task 残留
    会让第二条测试看到上一条的 pending_tool / current_plan。
    """
    from agent import core
    from agent.state import create_agent_state

    fresh = create_agent_state(
        system_prompt="test system prompt",
        model_name="test-model",
        review_enabled=False,
        max_recent_messages=6,
    )
    monkeypatch.setattr(core, "state", fresh)
    monkeypatch.setattr(core, "client", fake_client)
    # core.confirm_handlers 里 save_checkpoint 会写盘——用 stub 替掉避免污染真实磁盘
    from agent import checkpoint
    monkeypatch.setattr(checkpoint, "save_checkpoint", lambda s, source=None: None)
    monkeypatch.setattr(checkpoint, "clear_checkpoint", lambda: None)
    # response_handlers / tool_executor / task_runtime 也各自 import 了 save_checkpoint
    # 以模块名 from checkpoint import save_checkpoint 的拷贝形式引入——要挨个 patch
    from agent import response_handlers, tool_executor, task_runtime, confirm_handlers, session
    for mod in (response_handlers, tool_executor, task_runtime, confirm_handlers, session):
        if hasattr(mod, "save_checkpoint"):
            monkeypatch.setattr(mod, "save_checkpoint", lambda s, source=None: None)
        if hasattr(mod, "clear_checkpoint"):
            monkeypatch.setattr(mod, "clear_checkpoint", lambda: None)
    return fresh


def _register_test_tool(name: str, confirmation: str = "never", result: str = "ok"):
    """往 tool_registry 注册一个测试用工具。返回清理函数。"""
    from agent.tool_registry import TOOL_REGISTRY, register_tool

    def _tool(**kwargs):
        return result

    register_tool(
        name=name,
        description=f"test tool {name}",
        parameters={"arg": {"type": "string", "description": "anything"}},
        confirmation=confirmation,
    )(_tool)

    def cleanup():
        TOOL_REGISTRY.pop(name, None)

    return cleanup


def _planner_no_plan_response() -> FakeResponse:
    """构造 planner 的 'steps_estimate=1' 响应（让 chat 走单步分支）。"""
    return FakeResponse(
        content=[FakeTextBlock(text='{"steps_estimate": 1}')],
        stop_reason="end_turn",
    )


def _planner_two_step_response() -> FakeResponse:
    """构造 planner 的两步计划响应，用于验证计划确认 UI 事件。"""

    return FakeResponse(
        content=[
            FakeTextBlock(
                text=json.dumps({
                    "steps_estimate": 2,
                    "goal": "测试多步任务",
                    "thinking": "先读再写",
                    "needs_confirmation": True,
                    "steps": [
                        {
                            "step_id": "step-1",
                            "title": "读取",
                            "description": "读取输入",
                            "step_type": "read",
                            "suggested_tool": None,
                            "expected_outcome": "得到材料",
                            "completion_criteria": "材料已读取",
                        },
                        {
                            "step_id": "step-2",
                            "title": "报告",
                            "description": "生成报告",
                            "step_type": "report",
                            "suggested_tool": None,
                            "expected_outcome": "得到报告",
                            "completion_criteria": "报告已生成",
                        },
                    ],
                })
            )
        ],
        stop_reason="end_turn",
    )


# ---------- 测试 1：最简单的 end_turn ----------

def test_chat_single_turn_end_turn(monkeypatch):
    """用户输入 '你好'，planner 判单步，模型一次 end_turn 就收束。"""
    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),        # planner: 单步任务
            text_response("你好，我是 agent。"),  # executor: end_turn
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    reply = chat("你好")

    # reply 是"控制型 UI 文字"——普通 end_turn 应当为空串（正文已由流式输出打过）。
    # 模型正文正确性从 state.conversation.messages 里验证，不从 reply 验证。
    assert reply == "", f"end_turn reply 应为空（正文已流式输出），实际 {reply!r}"
    # 正文应在最后一条 assistant 消息里
    last_assistant = [m for m in state.conversation.messages if m["role"] == "assistant"][-1]
    assert "你好" in str(last_assistant["content"])
    # 最终状态：不处于 awaiting 任何东西
    assert state.task.status in ("idle", "running", "done")
    # planner + executor 各调了一次
    assert len(fake.create_requests) == 1   # planner 用 create
    assert len(fake.requests) == 1          # executor 用 stream


def test_chat_forwards_model_deltas_to_output_callback(monkeypatch, capsys):
    """deprecated on_output_chunk 兼容层仍能接收 assistant delta。

    RuntimeEvent 是新主路径；这个测试只保护旧调用方不被破坏。兼容层不能写
    checkpoint、runtime_observer、conversation.messages 或 Anthropic API messages，也
    不能变成新 UI 输出入口。
    """

    final_response = text_response("你好")

    class StreamingFakeStream:
        """模拟 Anthropic stream：先产出两个 text delta，再返回最终消息。"""

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter([
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(text="你"),
                ),
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(text="好"),
                ),
            ])

        def get_final_message(self):
            return final_response

    class StreamingFakeClient:
        """planner 走 create，executor 走带 delta 的 stream。"""

        def __init__(self):
            self.create_requests = []
            self.requests = []

            outer = self

            class _Messages:
                def create(self, **kwargs):
                    outer.create_requests.append(kwargs)
                    return _planner_no_plan_response()

                def stream(self, **kwargs):
                    outer.requests.append(kwargs)
                    return StreamingFakeStream()

            self.messages = _Messages()

    fake = StreamingFakeClient()
    _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    chunks = []
    reply = chat("你好", on_output_chunk=chunks.append)
    captured = capsys.readouterr()

    assert reply == ""
    assert chunks == ["你", "好"]
    assert "你好" not in captured.out
    assert len(fake.create_requests) == 1
    assert len(fake.requests) == 1


def test_chat_runtime_event_takes_precedence_over_output_callback(monkeypatch, capsys):
    """同时传 RuntimeEvent 和旧 output callback 时，只走 RuntimeEvent 主路径。

    这是第六阶段的防重复回归：旧 callback 是 deprecated compatibility bridge；
    一旦调用方提供 on_runtime_event，assistant.delta 不应再被转发到 on_output_chunk，
    避免 RuntimeEvent 主路径和旧 callback 双写同一段用户可见输出。
    """

    final_response = text_response("你好")

    class StreamingFakeStream:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            return iter([
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(text="你"),
                ),
                SimpleNamespace(
                    type="content_block_delta",
                    delta=SimpleNamespace(text="好"),
                ),
            ])

        def get_final_message(self):
            return final_response

    class StreamingFakeClient:
        def __init__(self):
            self.create_requests = []
            self.requests = []
            outer = self

            class _Messages:
                def create(self, **kwargs):
                    outer.create_requests.append(kwargs)
                    return _planner_no_plan_response()

                def stream(self, **kwargs):
                    outer.requests.append(kwargs)
                    return StreamingFakeStream()

            self.messages = _Messages()

    fake = StreamingFakeClient()
    _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    events = []
    chunks = []
    reply = chat(
        "你好",
        on_runtime_event=events.append,
        on_output_chunk=chunks.append,
    )
    captured = capsys.readouterr()

    assert reply == ""
    assert [event.text for event in events if event.event_type == "assistant.delta"] == [
        "你",
        "好",
    ]
    assert chunks == []
    assert captured.out == ""


def test_plan_confirmation_uses_runtime_event_not_stdout(monkeypatch, capsys):
    """计划确认提示应走 RuntimeEvent，而不是依赖 Textual stdout capture。"""

    fake = FakeAnthropicClient(responses=[_planner_two_step_response()])
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    events = []
    reply = chat("请分两步做", on_runtime_event=events.append)
    captured = capsys.readouterr()

    assert reply == ""
    assert state.task.status == "awaiting_plan_confirmation"
    plan_events = [
        event for event in events
        if event.event_type == "plan.confirmation_requested"
    ]
    assert len(plan_events) == 1
    assert "📋 任务规划：测试多步任务" in plan_events[0].text
    assert "按此计划执行吗？" in plan_events[0].text
    assert "按此计划执行吗？" not in captured.out


def test_chat_tool_confirmation_emits_display_event_with_file_preview(monkeypatch):
    """deprecated on_display_event 兼容层仍能接收 DisplayEvent。

    新主路径应使用 RuntimeEvent；这里只保护旧调用方继续收到工具确认 UI 投影，不改变
    pending_tool、checkpoint、conversation.messages 或 Anthropic tool_result 协议。
    """

    long_content = "第一行\n" + ("0123456789" * 80)
    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            tool_use_response(
                "write_file",
                {"path": "demo.md", "content": long_content},
                tool_id="T_WRITE",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    events = []
    reply = chat("写一个文件", on_display_event=events.append)

    assert reply == ""
    assert state.task.status == "awaiting_tool_confirmation"
    assert state.task.pending_tool["tool"] == "write_file"
    assert len(events) == 1
    event = events[0]
    assert event.event_type == "tool.awaiting_confirmation"
    assert event.metadata["tool"] == "write_file"
    assert event.metadata["path"] == "demo.md"
    assert event.metadata["content_length"] == len(long_content)
    assert "工具: write_file" in event.body
    assert "路径: demo.md" in event.body
    assert "内容预览" in event.body
    assert "是否执行？" in event.body
    assert len(event.metadata["content_preview"]) < len(long_content)


def test_request_user_input_emits_runtime_event(monkeypatch, capsys):
    """request_user_input 元工具暂停后，用户提示应通过 RuntimeEvent 投影。"""

    fake = FakeAnthropicClient(
        responses=[
            _planner_no_plan_response(),
            tool_use_response(
                "request_user_input",
                {
                    "question": "预算是多少？",
                    "why_needed": "用于制定方案",
                    "options": ["1000", "3000"],
                    "context": "旅行规划",
                },
                tool_id="T_INPUT",
            ),
        ]
    )
    state = _reset_core_module(monkeypatch, fake)

    from agent.core import chat

    events = []
    reply = chat("做旅行计划", on_runtime_event=events.append)
    captured = capsys.readouterr()

    assert reply == ""
    assert state.task.status == "awaiting_user_input"
    assert state.task.pending_user_input_request["question"] == "预算是多少？"
    request_events = [
        event for event in events
        if event.event_type == "user_input.requested"
    ]
    assert len(request_events) == 1
    assert "问题：预算是多少？" in request_events[0].text
    assert "可选项" in request_events[0].text
    assert "预算是多少？" not in captured.out


def test_new_question_after_confirmed_pending_tool_reenters_planning(monkeypatch):
    """旧 pending_tool 完成后，新 raw_text 不能被旧等待状态吞掉。"""

    cleanup = _register_test_tool("confirm_tool", confirmation="always", result="done")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                tool_use_response(
                    "confirm_tool",
                    {"arg": "x"},
                    tool_id="T_CONFIRM",
                ),
                text_response("工具已完成"),
                _planner_no_plan_response(),
                text_response("新问题回答"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        assert chat("先跑工具") == ""
        assert state.task.status == "awaiting_tool_confirmation"

        assert chat("y") == ""
        assert state.task.pending_tool is None

        assert chat("新的问题") == ""

        assert len(fake.create_requests) == 2
        assert fake.create_requests[-1]["messages"][-1]["content"] == "新的问题"
        assert any(
            message.get("role") == "user" and message.get("content") == "新的问题"
            for message in state.conversation.messages
        )
    finally:
        cleanup()


# ---------- 测试 2：一次 tool_use 循环 ----------

def test_chat_tool_use_cycle_completes(monkeypatch):
    """模型先返 tool_use，工具执行后再返 end_turn。

    关键点：模型第 2 次 request 里应当能看到第 1 次的 tool_use + tool_result 配对。
    """
    cleanup = _register_test_tool("test_echo", confirmation="never", result="echo-result")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                tool_use_response(
                    "test_echo", {"arg": "hi"}, tool_id="T1", text="我来调工具"
                ),
                text_response("调完了"),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        reply = chat("帮我跑个 echo")

        # reply 是控制型 UI 文字，普通 end_turn 应为空（正文走流式）
        assert reply == "", f"end_turn reply 应为空，实际 {reply!r}"
        # 正文验证：最后一条 assistant 消息应当含模型说的话
        last_assistant = [m for m in state.conversation.messages if m["role"] == "assistant"][-1]
        assert "调完了" in str(last_assistant["content"])
        # 验证第 2 次 request（stream 的第二次调用）里的 messages 结构
        second_request_messages = fake.requests[1]["messages"]

        # 应当同时包含 tool_use 和 tool_result，且 id 配对
        tool_use_ids = set()
        tool_result_ids = set()
        for msg in second_request_messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        assert tool_use_ids == tool_result_ids != set(), (
            f"tool_use 和 tool_result 必须一一配对，"
            f"got uses={tool_use_ids}, results={tool_result_ids}"
        )
    finally:
        cleanup()


# ---------- 测试 3：模型重复返回相同 tool_use，限流兜底是否触发 ----------

def test_chat_repeated_tool_use_hits_limit(monkeypatch):
    """模型病态地一直返回同一个 tool_use，MAX_TOOL_CALLS_PER_TURN 应当兜底。

    这是咱们昨晚 Kimi 那个死循环场景的"加速复现"版——
    真实环境里每次要用户按 y 确认，这里直接把工具设成 'never' 自动执行。
    断言：15 次后主循环退出，没有无限跑下去。
    """
    cleanup = _register_test_tool("loop_tool", confirmation="never", result="same-output")
    try:
        from agent.response_handlers import MAX_TOOL_CALLS_PER_TURN

        # 准备远超 limit 数量的 tool_use 响应，模型永远不说 end_turn
        canned = [_planner_no_plan_response()]
        for i in range(MAX_TOOL_CALLS_PER_TURN + 5):
            canned.append(
                tool_use_response("loop_tool", {"arg": "x"}, tool_id=f"T{i}")
            )
        canned.append(text_response("end"))   # 兜底，正常情况跑不到

        fake = FakeAnthropicClient(responses=canned)
        _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        reply = chat("让工具循环")

        # 应当命中 MAX_TOOL_CALLS_PER_TURN 或 MAX_LOOP_ITERATIONS，而不是无限
        assert (
            "工具调用次数过多" in reply
            or "循环次数过多" in reply
            or "重复工具调用过多" in reply
        ), (
            f"应该命中限流兜底，实际返回: {reply}"
        )
        # stream 调用次数应当被限制，不会用完所有预置响应
        assert len(fake.requests) <= MAX_TOOL_CALLS_PER_TURN + 2
    finally:
        cleanup()


# ---------- 测试 4：多 tool_use 并行，其中一个需确认 ----------

def test_chat_parallel_tool_use_fills_placeholder_for_skipped(monkeypatch):
    """模型一次返 2 个 tool_use，第 1 个 need-confirm，第 2 个立即跑。

    期望行为：
    - 第 1 个 tool 被挂起到 awaiting_tool_confirmation
    - 第 2 个 tool 不应该"也被执行"，应当写占位 tool_result
      （否则调用顺序不对，且会把半开事务搞乱）
    另一种可接受的实现是：第 1 个挂起后立刻 return，第 2 个 tool_use
    也补占位。关键是 messages 里两条 tool_use 都必须有对应的 tool_result。
    """
    cleanup1 = _register_test_tool("confirm_tool", confirmation="always", result="conf-out")
    cleanup2 = _register_test_tool("auto_tool", confirmation="never", result="auto-out")
    try:
        fake = FakeAnthropicClient(
            responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeTextBlock(text="我同时调两个工具"),
                        FakeToolUseBlock(
                            id="T_CONFIRM", name="confirm_tool", input={"arg": "a"}
                        ),
                        FakeToolUseBlock(
                            id="T_AUTO", name="auto_tool", input={"arg": "b"}
                        ),
                    ],
                    stop_reason="tool_use",
                ),
            ]
        )
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        reply = chat("跑两个工具")

        # 第一个需要确认，chat 应返回空串表示"等待用户"
        assert reply == "", f"等待用户确认时应返回空串，实际: {reply!r}"
        assert state.task.status == "awaiting_tool_confirmation"
        assert state.task.pending_tool is not None
        assert state.task.pending_tool["tool_use_id"] == "T_CONFIRM"

        # 关键断言：两个 tool_use 在 messages 里都必须有对应的 tool_result
        # （即使是占位 tool_result 也行）
        all_msgs = state.conversation.messages

        tool_use_ids = set()
        tool_result_ids = set()
        for msg in all_msgs:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_use":
                            tool_use_ids.add(block.get("id"))
                        elif block.get("type") == "tool_result":
                            tool_result_ids.add(block.get("tool_use_id"))

        # T_CONFIRM 在等确认，暂时可以没有配对；T_AUTO 应当已有结果（占位或真实）
        assert "T_AUTO" in tool_result_ids, (
            "紧随半开 tool_use 的后续并行 tool_use 必须有 tool_result（真实或占位），"
            f"当前 tool_result_ids={tool_result_ids}"
        )
    finally:
        cleanup1()
        cleanup2()
