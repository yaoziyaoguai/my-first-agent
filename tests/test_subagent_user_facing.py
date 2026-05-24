"""SubAgent user-facing CLI 命令测试（WP-C: SubAgent Meaningful Demo Delegation）。

中文学习边界：
- 验证 subagent registry 非空、用户可查看已注册子代理
- "show subagents" / "显示子代理" 是 CLI meta-command，经确定性字符串匹配处理
- "delegate to <name>: <task>" / "委托 <name>: <task>" 走 delegate_once()，
  复用已有 SubAgentRegistry + SubAgentRequest + execute_local 基础设施，
  不经过 tool pipeline、不调用 LLM、不新增 runtime flow
- 不触发真实 delegation、不执行 subagent、不调 LLM/API/private data
- 不新增 runtime flow
"""

from __future__ import annotations

import pytest

from agent.core import _looks_like_delegate_to_subagent, _looks_like_show_subagents


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


class TestDelegateToSubagentDetection:
    """_looks_like_delegate_to_subagent() 单元测试：验证 CLI meta-command 检测。

    中文学习边界：delegate to <name>: <task> / 委托 <name>: <task>
    是 deterministic CLI meta-command 检测，返回 (subagent_name, task)。
    不调用 LLM、不经过 tool pipeline、不执行 delegation。
    """

    def test_delegate_to_english(self):
        """'delegate to <name>: <task>' → 提取 name 和 task。"""
        result = _looks_like_delegate_to_subagent("delegate to demo-stat: count all files")
        assert result is not None
        name, task = result
        assert name == "demo-stat"
        assert "count all files" in task

    def test_delegate_to_chinese(self):
        """'委托 <name>: <task>' → 提取 name 和 task。"""
        result = _looks_like_delegate_to_subagent("委托 demo-stat: 统计项目文件")
        assert result is not None
        name, task = result
        assert name == "demo-stat"
        assert "统计项目文件" in task

    def test_delegate_to_chinese_colon(self):
        """'委托 <name>：<task>'（中文冒号）也触发。"""
        result = _looks_like_delegate_to_subagent("委托 demo-stat：统计文件")
        assert result is not None
        name, task = result
        assert name == "demo-stat"
        assert "统计文件" in task

    def test_delegate_task_to_name(self):
        """'delegate <task> to <name>' → 提取 name 和 task。"""
        result = _looks_like_delegate_to_subagent("delegate count files to demo-stat")
        assert result is not None
        name, task = result
        assert name == "demo-stat"
        assert "count files" in task

    def test_normal_text_not_detected(self):
        """普通文本不应被误判为 delegate 命令。"""
        assert _looks_like_delegate_to_subagent("hello world") is None
        assert _looks_like_delegate_to_subagent("show subagents") is None
        assert _looks_like_delegate_to_subagent("显示子代理") is None
        assert _looks_like_delegate_to_subagent("remember my name") is None

    def test_delegate_without_task_returns_none(self):
        """只有 'delegate to X' 但无 task 时返回 None。"""
        assert _looks_like_delegate_to_subagent("delegate to demo-stat") is None
        assert _looks_like_delegate_to_subagent("delegate to demo-stat:") is None
        assert _looks_like_delegate_to_subagent("委托 demo-stat：") is None


class TestChatDelegateToSubagentIntegration:
    """chat() + delegate to subagent CLI 命令集成测试。

    中文学习边界：delegate to X: task 走 delegate_once() 实际执行，
    不经过 tool pipeline、不调 LLM。
    """

    def test_delegate_to_demo_stat_returns_result(self):
        """委托 demo-stat 执行确定性任务，返回结构化结果。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("delegate to demo-stat: count all python files")
        assert isinstance(result, str)
        assert "[SubAgent: demo-stat]" in result
        assert "ok" in result

    def test_delegate_to_nonexistent_subagent_returns_hint(self):
        """委托不存在的子代理返回友好提示（含可用子代理列表）。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("delegate to nonexistent-subagent: do something")
        assert isinstance(result, str)
        assert "未找到" in result

    def test_delegate_chinese_returns_result(self):
        """'委托 demo-stat: 任务' 也走通。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("委托 demo-stat: 统计所有文件")
        assert isinstance(result, str)
        assert "[SubAgent: demo-stat]" in result

    def test_delegate_demo_stat_deterministic_ok(self):
        """demo-stat 对常规任务返回 ok + deterministic L0 summary。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("delegate to demo-stat: analyze project structure")
        assert "ok" in result
        assert "deterministic" in result.lower()

    def test_delegate_policy_blocked_shell(self):
        """shell/external process 任务被 L0 policy 阻止。"""
        import agent.tools  # noqa: F401
        from agent.core import chat

        result = chat("delegate to demo-stat: run shell command")
        assert "policy_blocked" in result.lower() or "Blocked" in result


class TestDelegateOnceE2E:
    """端到端：delegate_once() 通过 demo-stat subagent 执行确定性任务。

    中文学习边界：这些测试走完整的 SubAgentRegistry → SubAgentRequest →
    delegate_once → execute_local → SubAgentResult 链路。
    不调 LLM、不调 API、不执行真实外部进程、不修改 store。
    """

    def test_delegate_once_ok(self):
        """常规任务返回 ok + deterministic summary。"""
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry
        from agent.subagent_system.request import SubAgentRequest
        from agent.subagent_system.delegation import delegate_once

        root = Path("tests/fixtures/subagents")
        if not root.exists():
            pytest.skip("tests/fixtures/subagents 目录不存在")
        registry = SubAgentRegistry(roots=[root])
        d = registry.get_descriptor("demo-stat")
        assert d is not None

        request = SubAgentRequest(
            task="count files in project",
            role=d.role,
            allowed_tools=("read_file",),
            parent_trace_id="test-delegate-once-1",
            delegation_reason="test e2e",
            max_iterations=1,
        )
        run = delegate_once(request, registry)
        assert run.state == "completed"
        assert run.result is not None
        assert run.result.status == "ok"
        assert "deterministic" in run.result.summary.lower()

    def test_delegate_once_shell_blocked(self):
        """shell 任务被 L0 策略阻止。"""
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry
        from agent.subagent_system.request import SubAgentRequest
        from agent.subagent_system.delegation import delegate_once

        root = Path("tests/fixtures/subagents")
        if not root.exists():
            pytest.skip("tests/fixtures/subagents 目录不存在")
        registry = SubAgentRegistry(roots=[root])
        d = registry.get_descriptor("demo-stat")
        assert d is not None

        request = SubAgentRequest(
            task="run shell command to list files",
            role=d.role,
            allowed_tools=("read_file",),
            parent_trace_id="test-delegate-once-2",
            delegation_reason="test e2e blocked",
            max_iterations=1,
        )
        run = delegate_once(request, registry)
        assert run.result is not None
        assert run.result.status == "policy_blocked"

    def test_delegate_once_max_iterations_exceeded(self):
        """'loop until max' 任务触发 max_iterations_exceeded。"""
        from pathlib import Path
        from agent.subagent_system.registry import SubAgentRegistry
        from agent.subagent_system.request import SubAgentRequest
        from agent.subagent_system.delegation import delegate_once

        root = Path("tests/fixtures/subagents")
        if not root.exists():
            pytest.skip("tests/fixtures/subagents 目录不存在")
        registry = SubAgentRegistry(roots=[root])
        d = registry.get_descriptor("demo-stat")
        assert d is not None

        request = SubAgentRequest(
            task="loop until max iterations reached",
            role=d.role,
            allowed_tools=("read_file",),
            parent_trace_id="test-delegate-once-3",
            delegation_reason="test e2e max iterations",
            max_iterations=3,
        )
        run = delegate_once(request, registry)
        assert run.result is not None
        assert run.result.status == "max_iterations_exceeded"
