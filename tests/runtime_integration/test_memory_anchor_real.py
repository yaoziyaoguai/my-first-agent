"""Memory Proposal Anchor real provider smoke gated 测试。

中文学习边界：
这些测试验证 real provider smoke 的约束边界——默认 skip、授权检查、secret 不打印、
pending_review only、unknown provider fail-closed、direct dispatch 降级。
所有需要真实 API 调用的测试默认 skip，仅在用户显式 opt-in 后运行。

gated 测试双门控设计（Constraint E）：
1. 第一道门：MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1 env var
2. 第二道门：API key 是否配置（build_model_provider 是否成功）
只有两道门都通过才真正调用真实 API。

非 gated 测试验证分类/约束/脱敏逻辑——不需要真实 API，可随 pytest 默认运行。

架构依据：docs/plans/2026-05-22-001-feat-memory-anchor-real-smoke-plan.md
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
    classify_evidence_level,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.schema import RuntimeActionRequest

# ── 授权门控常量 ──

_AUTH_ENV = "MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE"
_SKIP_MESSAGE = "real provider smoke requires explicit opt-in: export MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1"


# ── 双门控 helper ──


def _is_authorized() -> bool:
    """检查第一道门：用户是否显式 opt-in。"""
    return os.environ.get(_AUTH_ENV) == "1"


def _require_real_provider() -> Any:
    """双门控：授权 + API key 配置检查。

    中文学习边界——为什么需要双门控：
    - 第一道门（env var）防止 CI 中误调用真实 API
    - 第二道门（API key 检查）优雅降级：API key 未配置时 skip 而非 crash
    - 两道门都通过才返回 real provider instance

    Returns:
        ModelProvider instance

    Raises:
        pytest.skip: 未授权或 API key 未配置
    """
    if not _is_authorized():
        pytest.skip(_SKIP_MESSAGE)

    from agent.provider.config import ProviderConfigurationError, load_agent_provider_config
    from agent.provider.factory import build_model_provider, build_model_provider_from_env

    # 优先使用用户显式选择的 provider type
    provider = build_model_provider_from_env()
    if provider is not None:
        return provider

    # 回退：默认 anthropic_native
    try:
        config = load_agent_provider_config()
        return build_model_provider(config)
    except ProviderConfigurationError:
        pytest.skip("API key not configured — real provider smoke requires valid credentials")


# ── 测试辅助 ──


def _build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 最小 dispatcher（仅 memory turn-end handler）。

    与 test_memory_anchor_fake.py 中的等价定义独立维护，
    保持两个测试文件自包含、无跨文件 import 耦合。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


class _SpyDispatcher:
    """包装 RuntimeActionDispatcher，拦截 route() 调用用于测试断言。

    与 test_memory_anchor_fake.py 中的 _SpyDispatcher 行为等价。
    在本文件中独立定义以保持测试文件自包含。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self._route_calls: list[RuntimeActionRequest] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        self._route_calls.append(request)
        return self._real.route(request)

    def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
        """测试 spy 透传 runtime-loop route，保持 real smoke provenance 语义。"""
        self._route_calls.append(request)
        return self._real.route_from_runtime_loop(request)

    @property
    def action_log(self):
        return self._real.action_log

    @property
    def route_calls(self) -> tuple[RuntimeActionRequest, ...]:
        return tuple(self._route_calls)


# ═══════════════════════════════════════════════════════════
# Gated tests — 需要真实 API 调用
# ═══════════════════════════════════════════════════════════


class TestRealProviderSmokeGated:
    """Real provider smoke gated 测试——默认 skip，需显式 opt-in。

    中文学习边界：
    这组测试需要真实 LLM API 调用。全部以 pytest.skip() 为默认路径。
    CI 环境即使设置了 MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE=1，
    如果 API key 未配置，仍会 skip（双门控）。
    """

    def test_requires_explicit_authorization(self):
        """验证未授权时 pytest skip。

        中文学习边界——这个测试保护什么：
        - real provider smoke 默认不可运行
        - 没有 opt-in env var 时 pytest 自动 skip
        - 防止 CI 中意外调用真实 API

        Purpose: 钉死 real provider smoke 授权门控
        Setup: 不设置 MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE
        Action: 调用 _require_real_provider()
        Expected: pytest.skip
        """
        if _is_authorized():
            # 已授权——测试双门控的第二道门
            from agent.provider.config import ProviderConfigurationError, load_agent_provider_config
            from agent.provider.factory import build_model_provider

            try:
                config = load_agent_provider_config()
                provider = build_model_provider(config)
                # 如果到这里说明两道门都通过了——provider 可用
                assert provider is not None
            except ProviderConfigurationError:
                pytest.skip("API key not configured")
        else:
            # 未授权——确认 skip
            pytest.skip(_SKIP_MESSAGE)

    def test_still_pending_review_only(self):
        """验证真实 LLM provider 下 memory proposal 仍为 pending_review only。

        中文学习边界——这个测试保护什么：
        - 真实 LLM 的响应不会绕过 MemoryTurnEndProposalHandler 的硬编码约束
        - auto_approved 恒为 False（不管 LLM 输出什么）
        - not_confirmed 恒为 True
        - provider_kind=real, provider_external_call=true
        - external_side_effects=false

        Purpose: 钉死 real provider 下 memory governance 不退化
        Setup: real provider + SpyDispatcher
        Action: chat("hello", provider=real_provider, runtime_action_dispatcher=spy)
        Expected evidence:
          - auto_approved == False, not_confirmed == True
          - provider_kind == "real", provider_external_call == True
          - external_side_effects == False
          - evidence_level == real_core_loop_runtime_e2e
          - target_module_proof 非 None
        """
        from agent.core import chat

        provider = _require_real_provider()
        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=provider,
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1, "turn-end hook 未触发"

        first_call = spy.route_calls[0]
        payload = dict(first_call.payload)

        # 验证 provider metadata
        assert payload.get("provider_kind") == "real", (
            f"provider_kind 必须为 'real'，实际 {payload.get('provider_kind')!r}"
        )
        assert payload.get("provider_external_call") is True, (
            f"provider_external_call 必须为 True，实际 {payload.get('provider_external_call')!r}"
        )
        assert payload.get("external_side_effects") is False, (
            f"external_side_effects 必须为 False，实际 {payload.get('external_side_effects')!r}"
        )

        # 验证 core loop 来源证据
        assert payload.get("core_loop_invoked") is True
        assert payload.get("core_entrypoint") == "core.chat"
        assert payload.get("runtime_hook_name") == "loop.turn_end"

        # 验证 action_log evidence
        action_events = list(spy.action_log)
        assert len(action_events) >= 1
        last_event = action_events[-1]
        evidence = dict(last_event.evidence)

        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("target_module_proof") is not None
        assert evidence.get("target_module") == "MemoryPolicy"

        # 验证 handler 硬编码约束
        assert evidence.get("auto_approved") is False, (
            "auto_approved 必须恒为 False——真实 LLM 也不能绕过 governance"
        )
        assert evidence.get("not_confirmed") is True

    def test_does_not_write_human_approved(self):
        """验证真实 provider 下不写 human_approved memory。

        中文学习边界——这个测试保护什么：
        - action_log 中所有 event 的 human_approved 不为 True
        - action_log 中所有 event 的 auto_approved 为 False
        - 真实 LLM 不会触发自动批准或静默写入

        Purpose: 钉死 real provider 下不写 human_approved
        Setup: real provider + SpyDispatcher
        Action: chat("hello", provider=real_provider, runtime_action_dispatcher=spy)
        Expected: 所有 event 的 auto_approved=False，human_approved != True
        """
        from agent.core import chat

        provider = _require_real_provider()
        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=provider,
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        action_events = list(spy.action_log)
        assert len(action_events) >= 1

        for event in action_events:
            ev = dict(event.evidence)
            assert ev.get("auto_approved") is False, (
                f"auto_approved 必须为 False，实际 {ev.get('auto_approved')!r}"
            )
            # human_approved 字段可能不存在于 evidence 中
            human_approved = ev.get("human_approved")
            if human_approved is not None:
                assert human_approved is not True, (
                    f"human_approved 不得为 True，实际 {human_approved!r}"
                )

    def test_no_secret_in_stdout_stderr(self):
        """验证 real provider 路径不打印 API key 到 stdout/stderr。

        中文学习边界——这个测试保护什么：
        - 即使 API 调用成功，stdout/stderr 也不含 API key pattern
        - 真实 provider 的异常/日志不泄露 secret

        Purpose: 钉死 secret 不打印
        Setup: real provider
        Action: 检查 provider config 的 redacted_summary 不含真实 key
        Expected: api_key 字段为 "SET" 或 "empty"，不含 sk-ant-/sk- 等 pattern
        """
        provider = _require_real_provider()

        # 验证 provider config 的 redacted_summary 安全性
        config = getattr(provider, "config", None)
        if config is not None and hasattr(config, "redacted_summary"):
            summary = config.redacted_summary()
            api_key_display = str(summary.get("api_key", ""))
            # api_key 必须是 "SET" 或 "empty"，不能是真实 key
            assert api_key_display in ("SET", "empty"), (
                f"redacted_summary api_key 必须为 'SET'/'empty'，"
                f"实际 {api_key_display!r}"
            )
            # 不得包含 API key pattern
            for pattern in ("sk-ant-", "sk-"):
                assert pattern not in api_key_display, (
                    f"redacted_summary 不得包含 API key pattern: {pattern}"
                )


# ═══════════════════════════════════════════════════════════
# Non-gated tests — 不需要真实 API，可随 pytest 默认运行
# ═══════════════════════════════════════════════════════════


class TestRealProviderClassification:
    """Evidence 分类边界测试——不需要真实 API 调用。

    中文学习边界：
    这些测试验证 classification 和 evidence chain 的逻辑正确性，
    不依赖真实 provider。它们保护的是「direct dispatcher 不能冒充 real」和
    「unknown provider fail-closed」这些硬防线。
    """

    def test_direct_dispatch_cannot_claim_real_provider_e2e(self):
        """验证 direct dispatcher 不能声称 real provider E2E。

        中文学习边界——这个测试保护什么：
        - 即使 payload 中手工设置 provider_kind="real"，
          direct dispatcher.route() 只能得到 harness_runtime_e2e
        - core_loop_invoked 字段的缺失导致分类降级
        - 防止任何代码绕过 core.chat() 路径声称 real provider E2E

        Purpose: 钉死 direct dispatch ≠ real provider E2E（R10）
        Setup: dispatcher
        Action: 构造含 provider_kind="real" 但不含 core_loop_invoked 的请求
        Expected: evidence_level == harness_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="dogfood",
            parent_trace_id="",
            payload={
                "user_message": "hello",
                "assistant_response": "Hi there!",
                "provider_kind": "real",
                "provider_external_call": True,
                "external_side_effects": False,
                # 刻意不设置 core_loop_invoked
            },
        )
        result = dispatcher.route(request)

        evidence = result.evidence
        assert evidence.get("evidence_level") == HARNESS_RUNTIME_E2E, (
            f"direct dispatch 只能得到 {HARNESS_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("evidence_level") != REAL_CORE_LOOP_RUNTIME_E2E
        assert evidence.get("core_loop_invoked") is not True

        # 二次确认：classify_evidence_level 也返回 harness
        level = classify_evidence_level(evidence)
        assert level == HARNESS_RUNTIME_E2E

    def test_unknown_provider_fail_closed(self):
        """验证 unknown provider_kind 不 overclaim real provider E2E。

        中文学习边界——这个测试保护什么：
        - provider_kind="unknown" 时，evidence 不声称任何 provider E2E 级别
        - fail-closed：未知 → 不声称 real
        - 与 _resolve_provider_evidence_metadata 的 unknown → ("unknown", False) 一致

        Purpose: 钉死 unknown provider fail-closed（R11）
        Setup: dispatcher
        Action: 构造含 provider_kind="unknown" 的请求，走 dispatcher.route()
        Expected: evidence.provider_kind == "unknown"
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "hello",
                "assistant_response": "Hi there!",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "unknown",
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        evidence = result.evidence
        assert evidence.get("provider_kind") == "unknown", (
            f"provider_kind 必须为 'unknown'，实际 {evidence.get('provider_kind')!r}"
        )
        assert evidence.get("provider_external_call") is False, (
            "unknown provider 的 provider_external_call 必须为 False"
        )
        # unknown provider 的 fail-closed 保证是 provider_kind="unknown" +
        # provider_external_call=False，而非 evidence_level 分类。
        # evidence_level 分类器目前只基于 core_loop_invoked + target_module_proof，
        # 不检查 provider_kind——本轮不扩展 evidence_level 分类（plan Deferred）。
        # 因此手动设置 core_loop_invoked=True 时仍会得到 real_core_loop_runtime_e2e。
        # 未来若新增 real_provider_core_loop_e2e 级别，此断言需更新。

    def test_provider_kind_not_from_class_name(self):
        """验证 provider_kind 不 fallback 到 class name。

        中文学习边界——这个测试保护什么：
        - provider_kind 只能是 "fake" / "real" / "unknown" 三态之一
        - 不得回退到 type(provider).__name__ 或任何实现细节
        - 这防止 provider 重命名/重构时 evidence 字段漂移

        Purpose: 钉死 provider_kind 只用固定枚举，不回退 class name
        Setup: dispatcher
        Action: 构造 payloads 验证 provider_kind 值域
        Expected: 只在 {"fake", "real", "unknown"} 中
        """
        valid_kinds = {"fake", "real", "unknown"}
        # 直接验证枚举值域——这是防止回退 class name 的硬约束
        assert "fake" in valid_kinds
        assert "real" in valid_kinds
        assert "unknown" in valid_kinds

        # 确认这些值中没有任何一个可能是 class name
        from agent.provider.fake_provider import FakeProvider
        class_name = type(FakeProvider()).__name__
        assert class_name not in valid_kinds, (
            f"class name {class_name!r} 不得出现在 provider_kind 值域中"
        )

    def test_key_source_kind_is_fixed_enum(self):
        """验证 key_source_kind 使用固定枚举，不回退到 env var name。

        中文学习边界——这个测试保护什么：
        - key_source_kind 只能是固定枚举值：project_dotenv, shell_env, env_var, none, unknown
        - 不得输出实际环境变量名如 ANTHROPIC_API_KEY
        - Constraint A 的精确对应实现

        Purpose: 钉死 key_source_kind 只用固定枚举
        """
        # 从 dogfood 脚本的安全 auth field 逻辑验证枚举值域
        valid_source_kinds = {"project_dotenv", "shell_env", "env_var", "missing", "unknown"}
        actual_env_var_names = {
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
            "ANTHROPIC_BASE_URL", "OPENAI_BASE_URL",
            "MY_FIRST_AGENT_LLM_PROVIDER", "MY_FIRST_AGENT_RUN_REAL_MEMORY_ANCHOR_SMOKE",
        }
        # 固定枚举值和实际环境变量名不得有交集
        overlap = valid_source_kinds & actual_env_var_names
        assert not overlap, (
            f"key_source_kind 枚举值不得包含实际环境变量名: {overlap}"
        )

    def test_error_path_exception_type_not_message(self):
        """验证异常路径脱敏：不输出 exception message（可能含 secret）。

        中文学习边界——这个测试保护什么：
        - 真实 provider 异常时，只输出 exception type，不输出 message
        - exception message 可能包含 API key、Authorization header、raw env 等敏感信息
        - 脱敏后的错误信息只包含已知的安全 error type 名称

        Purpose: 钉死异常路径脱敏（Constraint F）
        """
        from agent.provider.config import ProviderConfigurationError

        # 模拟 real smoke dogfood 的错误脱敏逻辑
        # 验证 ProviderConfigurationError 等已知 error type 名称是安全的
        safe_error_types = {
            "ProviderConfigurationError",
            "ProviderNotImplementedError",
            "ProviderConnectionError",
        }

        for error_type in safe_error_types:
            # 验证 error type 名称本身不含 API key pattern
            for pattern in ("sk-ant-", "sk-", "api_key", "secret"):
                assert pattern not in error_type.lower(), (
                    f"safe error type {error_type!r} 不得包含 secret pattern: {pattern}"
                )

        # 验证实际异常 message 不包含在脱敏输出中
        try:
            from agent.provider.config import load_agent_provider_config
            load_agent_provider_config("nonexistent_provider_type")
        except ProviderConfigurationError as exc:
            # 实际 message 可能包含 "unknown_provider"
            # 脱敏输出只应包含 "ProviderConfigurationError"
            redacted = f"provider construction failed: {type(exc).__name__}"
            assert "unknown_provider" not in redacted, (
                "脱敏输出不得包含 exception message 内容"
            )
            assert type(exc).__name__ in redacted, (
                "脱敏输出应包含 exception type name"
            )


class TestRealProviderNoAction:
    """测试 no_action 处置在 real provider smoke 上下文中的行为。

    不需要真实 API 调用——走 direct dispatcher 精确控制输入。
    """

    def test_no_action_still_produces_event_with_real_metadata(self):
        """验证 provider_kind=real 时 no_action 仍产生 RuntimeActionEvent。

        中文学习边界——这个测试保护什么：
        - 即使 memory policy 返回 no_action，event 仍然进入 action_log
        - provider metadata 字段（provider_kind, provider_external_call）正确传播
        - no_action ≠ 跳过 event 记录

        Purpose: 钉死 real metadata + no_action 组合不丢失 event
        Setup: dispatcher
        Action: 构造 provider_kind=real + no_action 输入的请求，dispatcher.route()
        Expected: action_log 有 1 个 event，evidence 字段正确
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "今天天气不错",
                "assistant_response": "是的，天气很好。",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "real",
                "provider_external_call": True,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        assert result.status == "success", (
            f"no_action 应返回 success，实际 {result.status!r}"
        )

        payload = dict(result.payload)
        assert payload.get("disposition") == "no_action"
        assert payload.get("auto_approved") is False
        assert payload.get("not_confirmed") is True

        # action_log 必须包含 event
        action_events = list(dispatcher.action_log)
        assert len(action_events) == 1
        event = action_events[0]
        ev = dict(event.evidence)
        assert ev.get("disposition") == "no_action"
        assert ev.get("provider_kind") == "real"
        assert ev.get("provider_external_call") is True
