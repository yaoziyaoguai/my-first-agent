"""多轮对话上下文累积测试（P2-2）。

验证 conversation.messages 在多轮 chat() 调用中正确累积，
且 API 请求包含完整历史上下文。
"""

from __future__ import annotations

from tests.conftest import (
    FakeAnthropicClient,
    FakeResponse,
    FakeTextBlock,
    FakeToolUseBlock,
    text_response,
)
from tests.test_main_loop import (
    _planner_no_plan_response,
    _register_test_tool,
    _reset_core_module,
)


class TestMultiTurnMessageAccumulation:
    """conversation.messages 在多轮对话中正确累积。"""

    def test_three_turns_messages_grow(self, monkeypatch):
        """三轮纯文本对话后 messages 应有 3 user + 3 assistant。

        每轮 chat() 调用 planner（1 次）+ 主模型（1 次）。
        """
        fake = FakeAnthropicClient(responses=[
            _planner_no_plan_response(),  # 第一轮 planner
            text_response("第一轮回复"),     # 第一轮 main
            _planner_no_plan_response(),  # 第二轮 planner
            text_response("第二轮回复"),     # 第二轮 main
            _planner_no_plan_response(),  # 第三轮 planner
            text_response("第三轮回复"),     # 第三轮 main
        ])
        state = _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("第一轮")
        assert len(state.conversation.messages) == 2
        assert state.conversation.messages[0] == {"role": "user", "content": "第一轮"}
        assert state.conversation.messages[1]["role"] == "assistant"

        chat("第二轮")
        assert len(state.conversation.messages) == 4
        assert state.conversation.messages[2] == {"role": "user", "content": "第二轮"}

        chat("第三轮")
        assert len(state.conversation.messages) == 6
        assert state.conversation.messages[4] == {"role": "user", "content": "第三轮"}

    def test_api_requests_include_prior_context(self, monkeypatch):
        """第三轮主模型请求应包含前两轮的 user/assistant 消息。"""
        fake = FakeAnthropicClient(responses=[
            _planner_no_plan_response(),
            text_response("第一轮回复"),
            _planner_no_plan_response(),
            text_response("第二轮回复"),
            _planner_no_plan_response(),
            text_response("第三轮回复"),
        ])
        _reset_core_module(monkeypatch, fake)

        from agent.core import chat

        chat("第一轮")
        chat("第二轮")
        chat("第三轮")

        # 第三轮主模型请求（requests[4]，因为每轮 planner + main 各一次）
        # planner 用 messages.create，main 用 messages.stream
        # FakeAnthropicClient 的 requests 记录 stream 调用，create_requests 记录 create 调用
        # 检查 main model 的 stream 请求
        stream_requests = fake.requests  # stream 调用
        assert len(stream_requests) >= 3  # 至少 3 次 main model 调用

        # 第三轮 stream 请求的 messages 应包含历史
        third_main_msgs = stream_requests[2]["messages"]
        user_contents = [
            m["content"] for m in third_main_msgs
            if m["role"] == "user" and isinstance(m["content"], str)
        ]
        assert "第一轮" in user_contents
        assert "第二轮" in user_contents
        assert "第三轮" in user_contents


class TestMultiTurnWithTools:
    """工具调用在多轮对话中正确累积。"""

    def test_tool_use_id_unique_across_turns(self, monkeypatch):
        """每一轮工具调用的 tool_use_id 应不同——验证多轮不混用 tool id。"""
        cleanup = _register_test_tool("unique_tool", confirmation="never", result="ok")
        try:
            fake = FakeAnthropicClient(responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeToolUseBlock(id="toolu_A", name="unique_tool", input={}),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("第一轮完成"),
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeToolUseBlock(id="toolu_B", name="unique_tool", input={}),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("第二轮完成"),
            ])
            _reset_core_module(monkeypatch, fake)

            from agent.core import chat

            chat("第一轮")
            chat("第二轮")

            # 请求中出现了两个不同的 tool_use id
            all_tool_use_ids = set()
            for req in fake.requests:
                for msg in req.get("messages", []):
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                all_tool_use_ids.add(block["id"])
            assert "toolu_A" in all_tool_use_ids
            assert "toolu_B" in all_tool_use_ids
        finally:
            cleanup()

    def test_messages_retain_tool_result_across_turns(self, monkeypatch):
        """工具执行结果保留在 messages 中，后续轮次可引用。"""
        cleanup = _register_test_tool("echo_tool", confirmation="never", result="done")
        try:
            fake = FakeAnthropicClient(responses=[
                _planner_no_plan_response(),
                FakeResponse(
                    content=[
                        FakeTextBlock(text="执行中"),
                        FakeToolUseBlock(id="T0", name="echo_tool", input={"arg": "hello"}),
                    ],
                    stop_reason="tool_use",
                ),
                text_response("工具已完成"),
                _planner_no_plan_response(),
                text_response("第二轮正常回复，引用之前的工具结果"),
            ])
            state = _reset_core_module(monkeypatch, fake)

            from agent.core import chat

            chat("第一轮")
            # 第二轮前 messages 至少包含 user1 + assistant1(tool_use)
            # + user2(tool_result) + assistant2
            msg_count_before = len(state.conversation.messages)
            assert msg_count_before >= 3  # user + assistant(tool_use) + user(tool_result)

            chat("第二轮")
            msg_count_after = len(state.conversation.messages)
            assert msg_count_after > msg_count_before  # 第二轮新增消息

            # 验证 tool_result 存在于 messages 中
            has_tool_result = False
            for msg in state.conversation.messages:
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            has_tool_result = True
            assert has_tool_result, "tool_result 应在 messages 中保留"
        finally:
            cleanup()
