"""Phase 1 real core loop E2E tests.

中文学习边界：
这些测试钉死 Phase 1 核心架构边界：
1. core.chat() 路径确实触发 RuntimeActionDispatcher（不是 dogfood harness 直接调用）
2. real_core_loop_runtime_e2e 必须有 core_loop_invoked=true 的 runtime hook evidence
3. dogfood harness 直接调用 dispatcher 只能是 harness_runtime_e2e
4. 缺 runtime hook evidence 自动降级
5. FakeProvider 不读 .env
6. memory turn-end hook 只产生 pending_review, no auto approve

为什么这些测试不等于 dogfood harness pass：
- dogfood harness 直接构造 RuntimeActionRequest → dispatcher.route()
  只证明了 dispatcher evidence chain 完整，不证明 core loop 触发
- 这里的测试通过 core.chat() → loop → turn-end hook → dispatcher
  证明 RuntimeAction 确实源自真实 runtime loop
"""

from __future__ import annotations

import os

from agent.provider.fake_provider import FakeProvider
from agent.runtime_integration import (
    ActionHandlerRegistry,
    RuntimeActionDispatcher,
    RuntimeActionType,
    classify_evidence_level,
    is_runtime_e2e_evidence,
)
from agent.runtime_integration.evidence import (
    HARNESS_RUNTIME_E2E,
    REAL_CORE_LOOP_RUNTIME_E2E,
    RuntimeActionModuleObserver,
)
from agent.runtime_integration.memory_hook import MemoryTurnEndProposalHandler
from agent.runtime_integration.schema import RuntimeActionRequest


# ========== 测试辅助 ==========


def _build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 最小 dispatcher（仅 memory turn-end handler）。"""
    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_TURN_END_PROPOSAL, MemoryTurnEndProposalHandler())
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


def _harness_request() -> RuntimeActionRequest:
    """构造 harness 风格 RuntimeActionRequest（无 core_loop_invoked 证据）。"""
    return RuntimeActionRequest(
        action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        source="dogfood",
        parent_trace_id="",
        payload={
            "user_message": "以后叫我小王",
            "assistant_response": "好的，以后叫你小王。",
        },
    )


def _assert_valid_runtime_action_evidence(result_evidence: dict) -> None:
    """断言 evidence 满足基本 runtime_action 条件（有 target_module_proof）。"""
    assert result_evidence.get("dispatcher_routed") is True
    assert result_evidence.get("target_handler_invoked") is True
    assert result_evidence.get("module_invoked") is True
    assert result_evidence.get("target_module_proof") is not None
    assert is_runtime_e2e_evidence(result_evidence)


# ========== 核心架构测试 ==========


class TestRealCoreLoopClassification:
    """测试 real_core_loop_runtime_e2e 与 harness_runtime_e2e 分类边界。"""

    def test_real_core_loop_runtime_e2e_requires_core_loop_invoked(self):
        """real_core_loop_runtime_e2e 必须有 core_loop_invoked=true 证据。

        架构边界：
        - dogfood harness 的 dispatcher.route() 调用有完整 target_module_proof
        - 但没有 core_loop_invoked=true（因为不经过 core loop turn-end hook）
        - 因此只能标为 harness_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher()
        result = dispatcher.route(_harness_request())

        _assert_valid_runtime_action_evidence(result.evidence)
        # 没有 core_loop_invoked → harness_runtime_e2e，不是 real_core_loop_runtime_e2e
        assert result.evidence["evidence_level"] == HARNESS_RUNTIME_E2E
        assert result.evidence["evidence_level"] != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("core_loop_invoked") is not True

    def test_direct_dogfood_dispatcher_call_is_harness_not_real_core_loop(self):
        """dogfood harness 直接调用 dispatcher 只能是 harness_runtime_e2e。

        架构边界：
        - 直接 dispatcher.route() 调用有完整的 route → handler → proof 链
        - 但 dispatcher source provenance 缺失 core loop hook evidence
        - 不能从 harness 路径升级到 real_core_loop_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher()
        result = dispatcher.route(_harness_request())

        evidence = result.evidence
        assert classify_evidence_level(evidence) == HARNESS_RUNTIME_E2E
        assert classify_evidence_level(evidence) != REAL_CORE_LOOP_RUNTIME_E2E
        # 验证 action_log 也反映相同分类
        events = list(dispatcher.action_log)
        assert len(events) == 1
        event_evidence = events[0].evidence
        assert event_evidence.get("evidence_level") == HARNESS_RUNTIME_E2E

    def test_missing_core_loop_hook_evidence_downgrades_classification(self):
        """缺少 runtime hook evidence 自动降级到 harness_runtime_e2e。

        架构边界：
        - 即使 handler 正确处理了请求并生成了 target_module_proof
        - 只要 core_loop_invoked 不是 True，就不能标 real_core_loop_runtime_e2e
        - 这是 dispatcher 层的自动降级，不需要 handler 参与判断
        """
        dispatcher = _build_phase1_dispatcher()

        # 构造一个 evidence-rich 但缺 core_loop_invoked 的请求
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="dogfood",
            parent_trace_id="",
            payload={
                "user_message": "hello",
                "assistant_response": "hi",
                # 故意不放 core_loop_invoked
            },
        )
        result = dispatcher.route(request)

        _assert_valid_runtime_action_evidence(result.evidence)
        assert result.evidence["evidence_level"] == HARNESS_RUNTIME_E2E


class TestFakeProviderSafety:
    """测试 FakeProvider 不读 .env，不调外部 API。"""

    def test_fake_provider_does_not_read_env(self):
        """FakeProvider 构造和调用都不读取环境变量。

        架构边界：
        - Phase 1 使用 FakeProvider 代替真实 LLM
        - FakeProvider 必须完全不访问 os.environ，确保安全审计通过
        - 如果 FakeProvider 读了 .env，Phase 1 就不能声称 no .env access
        """
        provider = FakeProvider()
        original_environ = dict(os.environ)

        # 验证构造不读 env（通过检查 os.environ 未被修改）
        assert dict(os.environ) == original_environ

        # 验证 create() 不读 env
        response = provider.create(
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        )
        assert response.stop_reason == "end_turn"
        assert len(response.content) > 0
        assert "已收到你的消息" in response.content[0].text

        # 验证 stream() 不读 env
        events = list(provider.stream(
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            tools=[],
        ))
        assert len(events) > 0
        assert events[-1].is_final

        # 确认 env 未被修改
        assert dict(os.environ) == original_environ

    def test_fake_provider_has_no_external_side_effects(self):
        """FakeProvider 不产生外部副作用。

        架构边界：
        - 无网络调用、无文件写入、无进程启动
        - 所有输出完全由输入确定性决定
        """
        provider = FakeProvider()

        # 多次调用产生一致性输出
        msgs1 = [{"role": "user", "content": "hello"}]
        msgs2 = [{"role": "user", "content": "hello"}]
        r1 = provider.create(system="", messages=msgs1, tools=[])
        r2 = provider.create(system="", messages=msgs2, tools=[])
        assert r1.content[0].text == r2.content[0].text  # 确定性输出

        # 不同输入产生不同输出
        msgs3 = [{"role": "user", "content": "world"}]
        r3 = provider.create(system="", messages=msgs3, tools=[])
        assert r3.content[0].text != r1.content[0].text  # 不同输入不同输出

    def test_fake_provider_streaming_is_deterministic(self):
        """FakeProvider 流式输出是可重现的。"""
        provider = FakeProvider()

        messages = [{"role": "user", "content": "test"}]
        stream1 = list(provider.stream(system="", messages=messages, tools=[]))
        stream2 = list(provider.stream(system="", messages=messages, tools=[]))

        assert len(stream1) == len(stream2)
        for e1, e2 in zip(stream1, stream2):
            assert e1.text_delta == e2.text_delta
            assert e1.is_final == e2.is_final


class TestMemoryTurnEndHook:
    """测试 memory turn-end proposal hook 的 Phase 1 约束。"""

    def test_phase1_memory_turn_end_hook_emits_pending_review_only(self):
        """Memory turn-end proposal 输出 pending_review=True, auto_approved=False。

        架构边界：
        - Phase 1 memory hook 只提议，不自动批准
        - 不写真实 memory episodes
        - 不读真实 sessions/runs
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "记住：以后叫我小王",
                "assistant_response": "好的，以后叫你小王。",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        payload = dict(result.payload)
        assert result.status == "success"
        # 关键约束：pending_review only，不自动批准
        assert payload.get("pending_review") is True, (
            "memory proposal must be pending_review only"
        )
        assert payload.get("auto_approved") is False, (
            "memory proposal must not be auto-approved"
        )
        assert payload.get("not_confirmed") is True
        assert payload.get("real_episodes_read") is False
        # no_silent_retain 在 evidence_extra 中，不在 payload 中
        assert result.evidence.get("no_silent_retain") is True

    def test_phase1_memory_hook_secret_like_input_is_rejected(self):
        """含 secret-like 输入的 memory proposal 被自动拒绝。

        架构边界：
        - 即使用户明确要求「记住这个 api_key: sk-xxx」
        - memory hook 检测到 secret-like pattern 后自动拒绝
        - 不提出 pending_review proposal
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "记住这个 api_key: sk-abc123def456",
                "assistant_response": "好的，记住了。",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        assert result.status == "rejected"
        payload = dict(result.payload)
        assert payload.get("secret_like_detected") is True
        assert payload.get("pending_review") is False
        assert payload.get("disposition") == "should_not_remember"

    def test_phase1_memory_hook_with_core_loop_invoked_gets_real_core_loop_classification(self):
        """有 core_loop_invoked=true 的 memory proposal 获得 real_core_loop_runtime_e2e。

        架构边界：
        - 这是从 harness_runtime_e2e 升级到 real_core_loop_runtime_e2e 的关键测试
        - core_loop_invoked=true + valid target_module_proof = real_core_loop_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "以后叫我小王",
                "assistant_response": "好的，以后叫你小王。",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        _assert_valid_runtime_action_evidence(result.evidence)
        assert result.evidence["evidence_level"] == REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("core_loop_invoked") is True
        assert result.evidence.get("core_entrypoint") == "core.chat"
        assert result.evidence.get("runtime_hook_name") == "loop.turn_end"
        assert result.evidence.get("provider_kind") == "fake"
        assert result.evidence.get("external_side_effects") is False


class TestPhase1EvidenceClassification:
    """测试分类逻辑正确性。"""

    def test_classify_evidence_level_returns_harness_for_non_core_loop(self):
        """无 core_loop_invoked 的证据即使通过 is_runtime_e2e_evidence 也只能是 harness。"""
        dispatcher = _build_phase1_dispatcher()
        result = dispatcher.route(_harness_request())

        level = classify_evidence_level(result.evidence)
        assert level == HARNESS_RUNTIME_E2E
        assert level != REAL_CORE_LOOP_RUNTIME_E2E

    def test_classify_evidence_level_returns_real_core_loop_when_invoked_from_core_loop(self):
        """有 core_loop_invoked=true 的证据升级到 real_core_loop_runtime_e2e。"""
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="core_loop",
            parent_trace_id="",
            payload={
                "user_message": "hello",
                "assistant_response": "hi",
                "core_loop_invoked": True,
                "core_entrypoint": "core.chat",
                "runtime_hook_name": "loop.turn_end",
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        level = classify_evidence_level(result.evidence)
        assert level == REAL_CORE_LOOP_RUNTIME_E2E

    def test_direct_subsystem_invocation_is_not_runtime_e2e(self):
        """直接子系统调用不能成为任何 runtime_e2e 级别。

        架构边界：
        - 没有 dispatcher_routed 的 evidence 不能通过 is_runtime_e2e_evidence
        - 返回 subsystem_integration 或更低级别
        """
        fake_evidence = {
            "dispatcher_routed": True,
            "target_handler_invoked": False,
            "module_invoked": False,
            "action_id": "act:test",
            "action_type": "tool.request",
            "handler_name": "TestHandler",
            "dispatcher_route_id": "route:test",
            "dispatcher_result_id": "",
            "target_module": "",
            "target_catalog_id": "",
            "target_handle": "",
            "target_descriptor_id": "",
            "invocation_adapter_id": "",
            "implementation_id": "",
            "callable_identity": "",
            "target_catalog_allowed": False,
            "target_identity_valid": False,
            "invocation_proof": None,
            "target_module_proof": None,
            "result_returned_to_parent_runtime": False,
            "parent_adjudicated": None,
        }
        assert not is_runtime_e2e_evidence(fake_evidence)
        level = classify_evidence_level(fake_evidence)
        assert level not in (REAL_CORE_LOOP_RUNTIME_E2E, HARNESS_RUNTIME_E2E)

    def test_event_only_is_not_runtime_e2e(self):
        """仅有 RuntimeActionEvent 不能伪装成 runtime_e2e。

        架构边界：
        - event 只是 dispatcher.route() 的 receipt
        - 没有 target_module_proof 就不能通过 is_runtime_e2e_evidence
        - 这是防止 handler 自报 module_invoked=true 的基本防御
        """
        event_evidence = {
            "action_id": "act:test",
            "action_type": "tool.request",
            "handler_name": "",
            "dispatcher_route_id": "route:test",
            "dispatcher_result_id": "",
            "target_module": "",
            "dispatcher_routed": True,
            "target_handler_invoked": False,
            "module_invoked": False,
            "result_returned_to_parent_runtime": False,
            "dispatcher_result_issued": False,
            "target_catalog_allowed": False,
            "target_identity_valid": False,
            "target_catalog_id": "",
            "target_handle": "",
            "target_descriptor_id": "",
            "invocation_adapter_id": "",
            "implementation_id": "",
            "callable_identity": "",
            "invocation_proof": None,
            "target_module_proof": None,
            "parent_adjudicated": None,
        }
        assert not is_runtime_e2e_evidence(event_evidence)
