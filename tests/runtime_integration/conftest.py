"""Runtime integration 测试专用 fixtures。

中文学习边界：
- state.conversation.messages 是模块级共享状态，多个测试文件累积消息
  超过 MAX_MESSAGES (100) 后会触发 compress_history()，而 compress 依赖
  真实的 Anthropic client。在 test suite 中 client 是 object() 替身，
  调用 client.messages.create() 必然 AttributeError。
- 这个 conftest 确保每个 runtime_integration 测试文件开始时 messages 清零，
  防止其他测试文件的消息累积导致历史压缩误触发。
- B7 Loop 4: ActiveSkillLifecycle 单例（_default_lifecycle）状态在测试间泄漏——
  test_i2 激活 skill 后 allowed_tools 持久化到下一个测试，导致工具被 __force_stop__。
  reset_lifecycle_state fixture 确保每个测试从干净 lifecycle 开始。
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


@pytest.fixture(autouse=True)
def _reset_lifecycle_state():
    """B7 Loop 4: 测试间清理 lifecycle 单例和全局 NS 状态。

    ActiveSkillLifecycle._default_lifecycle 是模块级单例——test_i2 在
    上面 activate skill 后，下一次测试的 tool gate 检查会读到前一个
    skill 的 allowed_tools → 工具被错误 __force_stop__。

    本 fixture 在每个测试前后：
    - 重置 default lifecycle 和 per-session registry（lifecycle.py）
    - 清除 _active_session_ns（skill_tool.py）
    - 重置 _active_skill / _skill_selected_by_model（core.py）
    """
    from agent.skill_system.lifecycle import reset_default_lifecycle
    from agent.skill_system.skill_tool import clear_active_session_ns
    import agent.core as _core

    reset_default_lifecycle()
    clear_active_session_ns()
    _core._active_skill = {}
    _core._skill_selected_by_model = False
    yield
    reset_default_lifecycle()
    clear_active_session_ns()
    _core._active_skill = {}
    _core._skill_selected_by_model = False
