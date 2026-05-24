"""SubAgent user-facing CLI 命令测试（WP-C: SubAgent Meaningful Demo Delegation）。

中文学习边界：
- 验证 subagent registry 非空、用户可查看已注册子代理
- "show subagents" / "显示子代理" 是 CLI meta-command，经确定性字符串匹配处理
- 不触发真实 delegation、不执行 subagent、不调 LLM/API/private data
- 不新增 runtime flow
"""

from __future__ import annotations

import pytest

from agent.core import _looks_like_show_subagents


class TestShowSubagentsDetection:
    """_looks_like_show_subagents() 单元测试：验证 CLI meta-command 检测。"""

    def test_show_subagents_english(self):
        assert _looks_like_show_subagents("show subagents")
        assert _looks_like_show_subagents("list subagents")
        assert _looks_like_show_subagents("show agents")

    def test_show_subagents_chinese(self):
        assert _looks_like_show_subagents("显示子代理")
        assert _looks_like_show_subagents("列出子代理")
        assert _looks_like_show_subagents("查看子代理")
        assert _looks_like_show_subagents("子代理列表")

    def test_normal_text_does_not_trigger(self):
        assert not _looks_like_show_subagents("hello")
        assert not _looks_like_show_subagents("delegate to subagent")
        assert not _looks_like_show_subagents("what can you do")

    def test_empty_or_whitespace_does_not_trigger(self):
        assert not _looks_like_show_subagents("")
        assert not _looks_like_show_subagents("   ")

    def test_partial_substring_does_not_trigger(self):
        # "子代理" 单独出现不应触发——需要完整触发短语
        assert not _looks_like_show_subagents("子代理")
        assert not _looks_like_show_subagents("subagents")


class TestSubagentListEvent:
    """subagent_list_event() 单元测试。"""

    def test_empty_descriptors(self):
        from agent.display_events import subagent_list_event

        event = subagent_list_event(())
        assert event.event_type == "subagent.listed"
        assert "暂无" in event.text

    def test_with_descriptors(self):
        from agent.display_events import subagent_list_event
        from agent.subagent_system.descriptor import SubAgentDescriptor

        descriptors = (
            SubAgentDescriptor(
                name="demo-stat",
                description="统计项目文件数量",
                role="analyzer",
                model="fake",
            ),
        )
        event = subagent_list_event(descriptors)
        assert event.event_type == "subagent.listed"
        assert "demo-stat" in event.text
        assert event.metadata["item_count"] == 1


@pytest.fixture(autouse=True)
def _reset_conversation_messages():
    """每次测试前清空模块级共享状态，防止跨文件累积影响 chat() 行为。"""
    from agent.core import state

    state.conversation.messages = []
    state.reset_task()
    yield
    state.conversation.messages = []
    state.reset_task()


class TestChatShowSubagentsIntegration:
    """chat() + show subagents CLI 命令集成测试。"""

    def test_chat_show_subagents_with_no_registry(self):
        """无 fixtures 目录情况下优雅降级（catch 异常返回空结果）。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("显示子代理")
        assert isinstance(result, str)

    def test_chat_show_subagents_english(self):
        """英文 'show subagents' 命令也通过统一入口工作。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("show subagents")
        assert isinstance(result, str)


class TestDemoSubagentRegistry:
    """验证 demo subagent 在 registry 中正确加载。"""

    def test_registry_has_demo_stat(self):
        """SubAgentRegistry 使用 tests/fixtures/subagents root 时包含 demo-stat。"""
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry

        root = Path("tests/fixtures/subagents")
        if not root.exists():
            pytest.skip("tests/fixtures/subagents 目录不存在")

        registry = SubAgentRegistry(roots=[root])
        visible = registry.list_visible()
        names = {d.name for d in visible}
        assert "demo-stat" in names

    def test_demo_stat_descriptor_fields(self):
        """demo-stat descriptor 各字段合法。"""
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry

        root = Path("tests/fixtures/subagents")
        if not root.exists():
            pytest.skip("tests/fixtures/subagents 目录不存在")

        registry = SubAgentRegistry(roots=[root])
        d = registry.get_descriptor("demo-stat")
        assert d is not None
        assert d.name == "demo-stat"
        assert d.status == "active"
        assert d.role == "analyzer"
        assert d.risk_level == "low"
        assert d.model == "fake"
