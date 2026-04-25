"""memory.compress_history + tool_registry 的集成测试。

覆盖：
- compress_history 在消息不超阈值时不压缩
- compress_history 在超阈值时触发 LLM summary 调用
- tool_registry 的三种 confirmation 模式（never / always / callable）
- execute_tool 异常兜底为字符串，不 raise
"""

from __future__ import annotations


from tests.conftest import FakeAnthropicClient, FakeResponse, FakeTextBlock


# ---------- compress_history ----------

def test_compress_history_no_op_under_threshold(monkeypatch):
    """消息条数和字符数都不超阈值时，应原样返回，不调 LLM。"""
    from agent import memory

    # 让阈值看起来很大，确保不会触发
    monkeypatch.setattr(memory, "MAX_MESSAGES", 1000)
    monkeypatch.setattr(memory, "MAX_MESSAGE_CHARS", 10_000_000)

    messages = [{"role": "user", "content": f"msg-{i}"} for i in range(5)]
    fake_client = FakeAnthropicClient(responses=[])   # 不应被调用

    new_msgs, new_summary = memory.compress_history(
        messages, fake_client, existing_summary=None, max_recent_messages=3
    )

    assert new_msgs == messages
    assert new_summary is None
    assert len(fake_client.create_requests) == 0


def test_compress_history_triggers_when_over_message_count(monkeypatch):
    """消息条数超阈值时，应当调 LLM 做摘要。"""
    from agent import memory

    # 把条数阈值压得很小
    monkeypatch.setattr(memory, "MAX_MESSAGES", 3)
    monkeypatch.setattr(memory, "MAX_MESSAGE_CHARS", 10_000_000)

    messages = [{"role": "user", "content": f"msg-{i}"} for i in range(10)]
    fake_client = FakeAnthropicClient(
        responses=[
            FakeResponse(
                content=[FakeTextBlock(text="这是摘要")],
                stop_reason="end_turn",
            )
        ]
    )

    new_msgs, new_summary = memory.compress_history(
        messages, fake_client, existing_summary=None, max_recent_messages=3
    )

    # 触发了一次 LLM 调用
    assert len(fake_client.create_requests) == 1
    # 摘要被存
    assert new_summary == "这是摘要"
    # recent 部分保留
    assert len(new_msgs) <= len(messages)


def test_compress_history_preserves_tool_pairing_boundary(monkeypatch):
    """压缩时不应切断 tool_use / tool_result 的配对边界。

    直接断言：压缩完 recent 部分里，任何 tool_result 都能在 recent 里找到对应 tool_use。
    """
    from agent import memory

    monkeypatch.setattr(memory, "MAX_MESSAGES", 3)
    monkeypatch.setattr(memory, "MAX_MESSAGE_CHARS", 10_000_000)

    messages = [
        {"role": "user", "content": "早期 1"},
        {"role": "user", "content": "早期 2"},
        {"role": "assistant", "content": [
            {"type": "tool_use", "id": "T1", "name": "read", "input": {}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "T1", "content": "结果"},
        ]},
        {"role": "user", "content": "最近 1"},
    ]
    fake_client = FakeAnthropicClient(
        responses=[
            FakeResponse(
                content=[FakeTextBlock(text="摘要文本")],
                stop_reason="end_turn",
            )
        ]
    )

    new_msgs, _ = memory.compress_history(
        messages, fake_client, existing_summary=None, max_recent_messages=2
    )

    # 收集 recent（new_msgs）里的所有 tool_use id 和 tool_result id
    tool_use_ids = set()
    tool_result_ids = set()
    for msg in new_msgs:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        tool_use_ids.add(block.get("id"))
                    elif block.get("type") == "tool_result":
                        tool_result_ids.add(block.get("tool_use_id"))

    # recent 里的每个 tool_result 都必须能找到对应 tool_use
    orphans = tool_result_ids - tool_use_ids
    assert not orphans, f"压缩后 recent 里有悬空 tool_result: {orphans}"


# ---------- tool_registry ----------

def test_needs_confirmation_never_returns_false():
    from agent.tool_registry import TOOL_REGISTRY, register_tool, needs_tool_confirmation

    @register_tool(
        name="never_tool",
        description="x",
        parameters={"arg": {"type": "string"}},
        confirmation="never",
    )
    def _t(**kw):
        return "ok"

    try:
        assert needs_tool_confirmation("never_tool", {"arg": "v"}) is False
    finally:
        TOOL_REGISTRY.pop("never_tool", None)


def test_needs_confirmation_always_returns_true():
    from agent.tool_registry import TOOL_REGISTRY, register_tool, needs_tool_confirmation

    @register_tool(
        name="always_tool",
        description="x",
        parameters={"arg": {"type": "string"}},
        confirmation="always",
    )
    def _t(**kw):
        return "ok"

    try:
        assert needs_tool_confirmation("always_tool", {"arg": "v"}) is True
    finally:
        TOOL_REGISTRY.pop("always_tool", None)


def test_needs_confirmation_callable_by_input():
    """callable confirmation 按 input 动态决定。"""
    from agent.tool_registry import TOOL_REGISTRY, register_tool, needs_tool_confirmation

    @register_tool(
        name="callable_tool",
        description="x",
        parameters={"path": {"type": "string"}},
        confirmation=lambda inp: inp.get("path", "").endswith(".env"),
    )
    def _t(**kw):
        return "ok"

    try:
        assert needs_tool_confirmation("callable_tool", {"path": "readme.md"}) is False
        assert needs_tool_confirmation("callable_tool", {"path": ".env"}) is True
    finally:
        TOOL_REGISTRY.pop("callable_tool", None)


def test_needs_confirmation_unknown_tool_defaults_true():
    """未注册的工具应当返回 True（保守：默认要确认）。"""
    from agent.tool_registry import needs_tool_confirmation
    assert needs_tool_confirmation("not_registered_tool", {}) is True


def test_execute_tool_catches_exception():
    """工具函数抛异常时，execute_tool 应当转成字符串返回，不 raise。

    回归防护：如果异常冒上去，会留下悬空 tool_use（没写 tool_result），
    下次 API 调用 400。
    """
    from agent.tool_registry import TOOL_REGISTRY, register_tool, execute_tool

    @register_tool(
        name="boom_tool",
        description="always raises",
        parameters={"arg": {"type": "string"}},
        confirmation="never",
    )
    def _boom(**kw):
        raise RuntimeError("故意抛错")

    try:
        result = execute_tool("boom_tool", {"arg": "x"})
        assert isinstance(result, str), (
            f"execute_tool 异常必须返回字符串，实际类型 {type(result)}"
        )
        assert "boom_tool" in result
        assert "故意抛错" in result or "RuntimeError" in result
    finally:
        TOOL_REGISTRY.pop("boom_tool", None)


def test_execute_tool_unknown_name_returns_string():
    """不在注册表里的 tool 名字，应当返回错误字符串而不是 raise。"""
    from agent.tool_registry import execute_tool

    result = execute_tool("totally_unknown_tool", {})
    assert isinstance(result, str)
    assert "totally_unknown_tool" in result
