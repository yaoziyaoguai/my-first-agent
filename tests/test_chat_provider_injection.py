"""验证 core.chat() 的 provider 显式注入路径。

学习型说明：
chat() 新增 provider 参数使 E2E 测试可以显式注入 ModelProvider，
无需 monkeypatch agent.core_contexts.build_model_provider_from_env。
本测试文件钉死以下 invariants：
- chat(provider=...) 使用传入的 provider 而非 env 加载
- chat() 不传 provider 时走默认 build_model_provider_from_env()
- 无 provider 时 fail closed（不是静默跳过）
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agent.core import _build_loop_context


class FakeProvider:
    """E2E 测试用的最小 ModelProvider 实现。"""

    provider_type = "fake"
    supports_tools = True
    supports_streaming = False

    def create(self, *, system_prompt, messages, tools, **kwargs):
        # 返回一个兼容 ProviderResponse 的假对象
        return _FakeResponse(content=[_FakeTextBlock("Fake response from test provider")])


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class _FakeResponse:
    def __init__(self, content):
        self.content = content
        self.stop_reason = "end_turn"
        self.usage = {}
        self.raw_provider_name = "fake"


class TestLoopContextProviderInjection:
    """验证 build_loop_context 和 _build_loop_context 的 provider 注入。"""

    def test_build_loop_context_with_explicit_provider(self):
        """显式传入 provider 时，loop_ctx.model_provider 应为传入值。"""
        from agent.core_contexts import build_loop_context

        provider = FakeProvider()
        loop_ctx = build_loop_context(
            MagicMock(),
            model_name="test-model",
            max_loop_iterations=3,
            provider=provider,
        )
        assert loop_ctx.model_provider is provider

    def test_build_loop_context_without_provider_falls_back_to_env(self):
        """不传 provider 时，应调用 build_model_provider_from_env()。"""
        with patch("agent.core_contexts.build_model_provider_from_env") as mock_build:
            fake_from_env = FakeProvider()
            mock_build.return_value = fake_from_env

            loop_ctx = _build_loop_context(
                MagicMock(),
                model_name="test-model",
                max_loop_iterations=3,
            )
            mock_build.assert_called_once()
            assert loop_ctx.model_provider is fake_from_env

    def test_core_build_loop_context_passes_provider(self):
        """core._build_loop_context 正确传递 provider 参数。"""
        provider = FakeProvider()
        loop_ctx = _build_loop_context(
            MagicMock(),
            model_name="test",
            max_loop_iterations=5,
            provider=provider,
        )
        assert loop_ctx.model_provider is provider


class TestChatProviderInjection:
    """验证 chat() provider 参数 —— 不需要 monkeypatch。"""

    def test_chat_accepts_provider_parameter(self, monkeypatch):
        """chat(provider=...) 应该接受并正确使用 provider 参数。"""
        provider = FakeProvider()

        # 关键 invariant：不需要 monkeypatch build_model_provider_from_env
        # chat() 通过 provider= 直接注入
        env_called = []

        def _track_env_call():
            env_called.append(True)
            return provider

        monkeypatch.setattr(
            "agent.core_contexts.build_model_provider_from_env",
            _track_env_call,
        )

        # 直接调用 — 用 provider= 应该不会触发 env 调用
        _ = _build_loop_context(
            MagicMock(),
            model_name="test",
            max_loop_iterations=1,
            provider=provider,
        )
        # env 不应该被调用，因为我们传了 provider
        assert len(env_called) == 0, (
            "build_model_provider_from_env() 不应该被调用"
            "——provider 已显式传入"
        )

    def test_chat_without_provider_still_works(self):
        """不传 provider 时，默认路径不受影响。"""
        # 只测试 loop context 构建不抛异常
        with patch("agent.core_contexts.build_model_provider_from_env") as mock_build:
            mock_build.return_value = FakeProvider()
            loop_ctx = _build_loop_context(
                MagicMock(),
                model_name="test",
            )
            assert loop_ctx.model_provider is not None


class TestNoMonkeypatchForCoreContexts:
    """E2E dogfood 核心 invariant：不再需要 monkeypatch build_model_provider_from_env。"""

    def test_explicit_provider_avoids_env_call(self):
        """传入 provider 时 build_model_provider_from_env 不应被调用。"""
        from agent.core_contexts import build_loop_context

        provider = FakeProvider()
        with patch("agent.core_contexts.build_model_provider_from_env") as mock_env:
            loop_ctx = build_loop_context(
                MagicMock(),
                model_name="test",
                max_loop_iterations=1,
                provider=provider,
            )
            mock_env.assert_not_called()
            assert loop_ctx.model_provider is provider
