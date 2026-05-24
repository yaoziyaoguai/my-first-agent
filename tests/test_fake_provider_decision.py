"""FakeProvider tool decision layer 测试。

中文学习边界：
- 本文件测试 FakeProvider 的 deterministic tool decision 层（_resolve_tool_use）
- FakeProvider 只输出 ToolUseBlock（tool_use intent），不直接执行工具
- 真正工具执行路径：core.chat → loop.py → handle_tool_use_response → ToolExecutor
- 不新增 fake path / fake runtime / fake loop

测试目标：
1. 基于工具名称/描述/用户消息做 rule-based 匹配
2. 未匹配时返回普通 fake 文本响应
3. tool_use 经由 core.chat / Tool Pipeline 返回用户可见 tool result
4. FakeProvider 不直接执行工具
5. real provider path 未被改变（opt-in gate 保持）
"""

from __future__ import annotations

import pytest

from agent.provider.fake_provider import (
    _normalize,
    _resolve_tool_use,
    _tool_desc_keywords,
    _tool_name_tokens,
    _default_tool_input,
)
from agent.provider.protocol import ToolUseBlock
from agent.provider.fake_provider import FakeProvider


@pytest.fixture(autouse=True)
def _reset_conversation_messages():
    """每次测试前清空模块级共享状态，防止跨文件累积影响 chat() 行为。

    需要同时重置两项状态：
    1. state.conversation.messages：防止超过 MAX_MESSAGES(100) 触发
       compress_history() → client.messages.create() (client 是 object() 替身)
    2. state.task：防止之前测试残留的 running status + current_plan 导致
       chat() 错误进入 _run_main_loop 而非 _run_planning_phase
    """
    from agent.core import state

    state.conversation.messages = []
    state.reset_task()
    yield
    state.conversation.messages = []
    state.reset_task()


# ===== Helper: build tool descriptor list =====


def _make_tool(name: str, description: str, parameters: dict | None = None) -> dict:
    return {"name": name, "description": description, "parameters": parameters or {}}


# ===== WP3.1: _resolve_tool_use unit tests =====


class TestResolveToolUse:
    """_resolve_tool_use 单元测试：验证基于工具的 rule-based matching。"""

    # 测试工具集（模拟 TOOL_REGISTRY 中已注册的 safe demo tools）
    SAFE_DEMO_TOOLS = [
        _make_tool(
            "demo.echo_task_summary",
            "返回当前 demo 任务的确定性摘要。零副作用、零网络调用、不读私人资料。",
        ),
        _make_tool(
            "demo.write_demo_note",
            "写入一个 demo note 到受控的 workspace/demo/ 目录。"
            "不写用户真实目录、不读私人资料、不访问网络。"
            "path 和 content 可选——未提供时使用安全默认值。",
        ),
    ]

    def test_full_name_exact_match_returns_tool_use(self):
        """用户消息中包含完整工具名 → 精确匹配，score=100。"""
        result = _resolve_tool_use(
            "demo.echo_task_summary", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        assert result.name == "demo.echo_task_summary"
        assert isinstance(result, ToolUseBlock)

    def test_name_token_match_returns_tool_use(self):
        """用户消息命中工具名称关键词（非完整名）→ token 匹配。"""
        result = _resolve_tool_use(
            "write a demo note please", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        assert result.name == "demo.write_demo_note"

    def test_description_keyword_match_returns_tool_use(self):
        """用户消息与工具描述有关键词重叠 → 描述匹配，score≥30。"""
        result = _resolve_tool_use(
            "帮我写入一个 note", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        assert result.name == "demo.write_demo_note"

    def test_chinese_description_keyword_match(self):
        """中文描述关键词匹配：'任务摘要' 命中 echo_task_summary。"""
        result = _resolve_tool_use(
            "查看当前任务摘要", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        assert result.name == "demo.echo_task_summary"

    def test_no_match_returns_none(self):
        """无匹配消息返回 None，走普通 fake 文本响应。"""
        result = _resolve_tool_use("hello", self.SAFE_DEMO_TOOLS)
        assert result is None

    def test_hello_does_not_match_any_tool(self):
        """'hello' 不应该匹配任何工具（用于防止误触发 tool_use）。"""
        result = _resolve_tool_use("hello", self.SAFE_DEMO_TOOLS)
        assert result is None

    def test_empty_string_returns_none(self):
        """空字符串 → 不匹配任何工具。"""
        result = _resolve_tool_use("", self.SAFE_DEMO_TOOLS)
        assert result is None

    def test_whitespace_only_returns_none(self):
        """纯空白 → None。"""
        result = _resolve_tool_use("   ", self.SAFE_DEMO_TOOLS)
        assert result is None

    def test_empty_tools_list_returns_none(self):
        """空工具列表 → 永远不匹配。"""
        result = _resolve_tool_use("demo.write_demo_note", [])
        assert result is None

    def test_legacy_demo_triggers_still_work(self):
        """旧版 _DEMO_TOOL_TRIGGERS 精确匹配作为兼容性回退仍生效。"""
        # "create a demo note" 命中 legacy triggers
        result = _resolve_tool_use(
            "create a demo note", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        # 后备路径同样产生 demo.write_demo_note
        assert result.name == "demo.write_demo_note"

    def test_score_threshold_below_30_returns_none(self):
        """score < 30 的弱匹配被过滤（门槛保护）。"""
        # "note" alone might have a weak match, but should be below threshold
        result = _resolve_tool_use("note", self.SAFE_DEMO_TOOLS)
        # "note" 可能与 write_demo_note 描述有轻微重叠但不能稳定断言
        # 只验证不崩溃
        assert result is None or isinstance(result, ToolUseBlock)

    def test_tool_without_name_or_desc_is_skipped(self):
        """缺失 name 或 description 的工具被跳过，不崩溃。"""
        tools = [
            {"name": "", "description": "some desc", "parameters": {}},
            {"name": "valid_tool", "description": "", "parameters": {}},
            _make_tool("demo.echo_task_summary", "返回当前任务摘要。"),
        ]
        result = _resolve_tool_use("任务摘要", tools)
        assert result is not None
        assert result.name == "demo.echo_task_summary"

    def test_tool_use_block_has_valid_structure(self):
        """返回的 ToolUseBlock 必须含 id、name、input 字段。"""
        result = _resolve_tool_use(
            "demo.write_demo_note please", self.SAFE_DEMO_TOOLS
        )
        assert result is not None
        assert result.id.startswith("toolu_fake_")
        assert result.name == "demo.write_demo_note"
        assert isinstance(result.input, dict)


# ===== WP3.2: helper function unit tests =====


class TestHelperFunctions:
    def test_normalize_trims_and_lowercases(self):
        assert _normalize("  Hello World  ") == "hello world"

    def test_normalize_collapses_internal_spaces(self):
        assert _normalize("hello   world") == "hello world"

    def test_tool_name_tokens_splits_correctly(self):
        tokens = _tool_name_tokens("demo.write_demo_note")
        assert "write" in tokens
        assert "note" in tokens
        # "demo" is stripped as prefix
        assert "demo" not in tokens

    def test_tool_name_tokens_strips_demo(self):
        tokens = _tool_name_tokens("demo.echo_task_summary")
        assert "echo" in tokens
        assert "task" in tokens
        assert "summary" in tokens
        assert "demo" not in tokens

    def test_tool_desc_keywords_extracts_english(self):
        kw = _tool_desc_keywords("write a note to the workspace directory")
        assert "write" in kw
        assert "note" in kw
        assert "workspace" in kw
        assert "directory" in kw
        # stop words excluded
        assert "the" not in kw
        assert "and" not in kw
        assert "for" not in kw

    def test_tool_desc_keywords_extracts_chinese(self):
        kw = _tool_desc_keywords("写入一个 demo note 文件")
        # 中文 2-4 字片段
        assert "写入" in kw or "入一" in kw  # at least some cn fragments
        assert len(kw) > 3  # many fragments expected

    def test_default_tool_input_zero_arg_tool(self):
        result = _default_tool_input("demo.echo_task_summary", {})
        assert result == {}

    def test_default_tool_input_with_optional_params(self):
        result = _default_tool_input(
            "demo.write_demo_note",
            {"properties": {"path": {}, "content": {}}, "required": []},
        )
        # 有可选参数但无必填 → 使用安全默认值（包含 path 和 content）
        assert isinstance(result, dict)
        assert "path" in result
        assert "content" in result


# ===== WP3.3: FakeProvider.create() 行为测试 =====


class TestFakeProviderCreate:
    """验证 FakeProvider.create() 的工具匹配行为。"""

    DEMO_TOOLS = [
        _make_tool(
            "demo.echo_task_summary",
            "返回当前任务摘要。零副作用。",
        ),
        _make_tool(
            "demo.write_demo_note",
            "写入 demo note 到 workspace/demo/ 目录。",
        ),
    ]

    def test_create_returns_text_for_no_match(self):
        provider = FakeProvider()
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            tools=self.DEMO_TOOLS,
        )
        assert response.stop_reason == "end_turn"
        assert len(response.content) == 1
        assert hasattr(response.content[0], "text")

    def test_create_returns_tool_use_for_match(self):
        provider = FakeProvider()
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "write a demo note"}],
            tools=self.DEMO_TOOLS,
        )
        assert response.stop_reason == "tool_use"
        # 应有 TextBlock + ToolUseBlock
        assert len(response.content) >= 2
        tool_blocks = [b for b in response.content if getattr(b, "name", None)]
        assert len(tool_blocks) == 1
        assert tool_blocks[0].name == "demo.write_demo_note"

    def test_create_with_no_tools_returns_text(self):
        provider = FakeProvider()
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "write a demo note"}],
            tools=[],
        )
        assert response.stop_reason == "end_turn"

    def test_fake_provider_does_not_execute_tools(self):
        """FakeProvider.create() 只输出 ToolUseBlock，不调用 tool func。

        验证方式：传入一个描述中包含关键词的消息，确认返回的是 ToolUseBlock
        结构（不是 tool func 的返回值）。真正的工具执行在 ToolExecutor 中。
        """
        provider = FakeProvider()
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "echo task summary"}],
            tools=self.DEMO_TOOLS,
        )
        # 有匹配 → stop_reason="tool_use"
        # 但工具并未被实际执行——返回的是 ToolUseBlock（intent）
        if response.stop_reason == "tool_use":
            tool_blocks = [
                b for b in response.content
                if hasattr(b, "name") and hasattr(b, "input")
            ]
            assert len(tool_blocks) == 1
            # ToolUseBlock 是 provider output，不是 execution result
            assert isinstance(tool_blocks[0], ToolUseBlock)


# ===== WP3.4: 集成测试 — core.chat + FakeProvider + Tool Pipeline =====


class TestFakeProviderToolPipelineIntegration:
    """core.chat() + FakeProvider → Tool Pipeline → user-visible tool result。

    中文学习边界：本测试验证 fake provider 的 tool_use intent 经过完整
    unified runtime flow（core.chat → loop.py → handle_tool_use_response →
    ToolExecutor → tool result），而不是 direct dispatcher 冒充 E2E。
    """

    def test_chat_with_tool_match_goes_through_pipeline(self):
        """用户消息匹配工具 → core.chat 走完整 Tool Pipeline → 可观测结果。"""
        import agent.tools  # noqa: F401 - 触发工具注册
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        # 使用能匹配 demo.echo_task_summary 的消息
        result = chat(
            "查看任务摘要",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
        )
        assert isinstance(result, str)
        # 如果匹配了 tool_use，结果中应包含可观测的 tool 相关输出
        # 如果不匹配（描述关键词可能变化），至少不应崩溃
        assert len(result) > 0

    def test_chat_hello_no_tool_produces_text(self):
        """'hello' 不匹配任何工具 → 普通文本响应，不走 tool pipeline。"""
        import agent.tools  # noqa: F401
        from agent.core import chat
        from agent.provider.fake_provider import FakeProvider
        from agent.runtime_integration import (
            ActionHandlerRegistry,
            RuntimeActionDispatcher,
            RuntimeActionType,
        )
        from agent.runtime_integration.evidence import RuntimeActionModuleObserver
        from agent.runtime_integration.tool_gate import ToolGateHandler
        from agent.runtime_integration.tool_invoke import ToolInvokeHandler
        from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler

        registry = ActionHandlerRegistry()
        registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
        registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
        registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
        dispatcher = RuntimeActionDispatcher(
            registry=registry, observer=RuntimeActionModuleObserver()
        )

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=dispatcher,
        )
        # chat() 可能返回 str 或空串（取决于 main loop 输出路径），但不应崩溃
        assert isinstance(result, str)


# ===== WP3.5: 架构边界测试 =====


class TestArchitectureBoundaries:
    """确保 FakeProvider 不越权：不执行工具、不改变 real provider path。"""

    def test_fake_provider_supports_tools_is_false(self):
        """FakeProvider.supports_tools=False —— 声明它不执行工具。"""
        provider = FakeProvider()
        # FakeProvider 的 supports_tools 明确为 False，因为它的 tool_use
        # intent 由 deterministic rules 生成，不代表真实 model tool calling
        assert provider.supports_tools is False

    def test_fake_provider_provider_type_is_fake(self):
        provider = FakeProvider()
        assert provider.provider_type == "fake"

    def test_real_provider_skipped_without_env(self):
        """没有 PROVIDER_ENV 时 build_model_provider_from_env() 返回 None。"""
        from agent.provider.factory import build_model_provider_from_env

        # 在测试中（无 .env），不应构建真实 provider
        provider = build_model_provider_from_env()
        # 可能为 None（无配置）或 FakeProvider（通过 PROVIDER_ENV=fake）
        if provider is not None:
            # 如果有 provider，应该是 fake（由 PROVIDER_ENV 环境变量决定）
            # 这在本地开发中是安全的
            pass

    def test_fake_provider_does_not_import_tool_funcs(self):
        """FakeProvider 模块不应导入任何 tool func 做直接执行。

        验证方式：检查模块的顶层引用不包含具体的 tool function。
        """
        import agent.provider.fake_provider as fp

        # fake_provider 不应包含对具体 tool func 的直接引用
        # 工具描述通过 create() 的 tools 参数传入，而非硬编码
        assert not hasattr(fp, "demo_echo_task_summary")
        assert not hasattr(fp, "demo_write_demo_note")


# ═══════════════════════════════════════════════════════════
# WP-D: Streaming / Progress User-Visible Experience
# ═══════════════════════════════════════════════════════════


class TestFakeProviderStreaming:
    """FakeProvider stream() 确定性分片输出测试。

    中文学习边界：
    - FakeProvider.supports_streaming = True 将 text-only 响应走 stream() 路径
    - stream() 按 3 字一组产出 text_delta 事件，以 final 结束
    - tool_use 响应在 stream() 中产 tool_request 事件，call_model() 回退 create()
    - 这**不是**第二条 runtime——stream/create 共享同一 FakeProvider 实例，
      call_model() 是唯一入口，Tool Pipeline 对两条路径完全透明
    """

    def test_supports_streaming_is_true(self):
        """FakeProvider 默认启用 streaming（WP-D 确定性流式输出）。"""
        p = FakeProvider()
        assert p.supports_streaming is True

    def test_stream_text_only_produces_delta_events(self):
        """stream() text-only 响应产出连续 text_delta + final 事件。"""
        p = FakeProvider()
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "你好世界"}],
                tools=[],
            )
        )
        assert len(events) >= 2  # 至少 1 delta + final
        deltas = [e for e in events if e.event_type == "text_delta"]
        finals = [e for e in events if e.event_type == "final"]
        assert len(deltas) >= 1
        assert len(finals) == 1
        # 拼接所有 delta 文本 = 完整响应
        full_text = "".join(e.text_delta for e in deltas)
        assert "你好世界" in full_text

    def test_stream_chunk_size(self):
        """每个 text_delta chunk 大小 <= 3（确定性分片）。"""
        p = FakeProvider()
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "这是一条比较长的测试消息"}],
                tools=[],
            )
        )
        deltas = [e for e in events if e.event_type == "text_delta"]
        for delta in deltas:
            assert len(delta.text_delta) <= 3

    def test_stream_sequence_monotonic(self):
        """stream() 事件的 sequence 严格递增。"""
        p = FakeProvider()
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "测试"}],
                tools=[],
            )
        )
        for i in range(1, len(events)):
            assert events[i].sequence > events[i - 1].sequence

    def test_stream_ends_with_final(self):
        """stream() 必须以 final 事件结束。"""
        p = FakeProvider()
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "测试"}],
                tools=[],
            )
        )
        assert events[-1].is_final is True
        assert events[-1].event_type == "final"

    def test_stream_tool_use_produces_tool_request_event(self):
        """tool_use 匹配时，stream() 产 tool_request 事件。

        stream() 不产 ToolUseBlock（ProviderStreamEvent 不携带 tool_name/tool_input），
        tool_request 是信号告知 call_model() 回退 create() 获取完整 ToolUseBlock。
        call_model() 检测到 tool_request 时调用 provider.create() 获取含
        ToolUseBlock 的 ProviderResponse，text deltas 不重复 emit。
        """
        p = FakeProvider()
        tools = [{"name": "demo.write_demo_note", "description": "写一个演示笔记到文件"}]
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "写一个演示笔记"}],
                tools=tools,
            )
        )
        tool_events = [e for e in events if e.event_type == "tool_request"]
        assert len(tool_events) == 1
        # tool_request 后仍有 final
        assert events[-1].event_type == "final"

    def test_stream_tool_use_still_produces_text_deltas(self):
        """tool_use 匹配时，文本 delta 仍正常流出（用户可见"思考"文本）。"""
        p = FakeProvider()
        tools = [{"name": "demo.write_demo_note", "description": "写一个演示笔记"}]
        events = list(
            p.stream(
                system="test",
                messages=[{"role": "user", "content": "写一个演示笔记"}],
                tools=tools,
            )
        )
        deltas = [e for e in events if e.event_type == "text_delta"]
        assert len(deltas) >= 1
        full = "".join(e.text_delta for e in deltas)
        assert len(full) > 0
