"""Runtime integration 测试专用 fixtures。

中文学习边界：
- state.conversation.messages 是模块级共享状态，多个测试文件累积消息
  超过 MAX_MESSAGES (100) 后会触发 compress_history()，而 compress 依赖
  真实的 Anthropic client。在 test suite 中 client 是 object() 替身，
  调用 client.messages.create() 必然 AttributeError。
- 这个 conftest 确保每个 runtime_integration 测试文件开始时 messages 清零，
  防止其他测试文件的消息累积导致历史压缩误触发。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_conversation_messages():
    """每次测试前清空模块级 state.conversation.messages，防止跨文件消息累积。

    测试自身负责构造所需的消息上下文；本 fixture 只做隔离，不构造消息。
    """
    from agent.core import state

    state.conversation.messages = []
    yield
    state.conversation.messages = []
