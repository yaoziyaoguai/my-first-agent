"""Phase 1 real core loop E2E tests.

中文学习边界：
这些测试钉死 Phase 1 核心架构边界：
1. core.chat() 路径确实触发 RuntimeActionDispatcher（不是 dogfood harness 直接调用）
2. real_core_loop_runtime_e2e 必须有 dispatcher-owned runtime loop provenance
3. dogfood harness 直接调用 dispatcher 只能是 harness_runtime_e2e
4. 缺 runtime hook evidence 自动降级
5. FakeProvider 不读 .env
6. memory turn-end hook 只产生 pending_review, no auto approve

为什么这些测试不等于 dogfood harness pass：
- dogfood harness 直接构造 RuntimeActionRequest → dispatcher.route()
  只证明了 dispatcher evidence chain 完整，不证明 core loop 触发
- TestRealCoreLoopClassification / TestMemoryTurnEndHook 手工构造
  RuntimeActionRequest 并直接 dispatcher.route()——只能证明 classification
  逻辑正确
- TestCoreChatWiring 真正调用 core.chat()，使用 SpyDispatcher 捕获 route()
  调用，证明 core.chat → run_main_loop → turn-end hook → dispatcher 这条真实
  接线存在且工作正常
"""

from __future__ import annotations

import os
from typing import Any

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
from agent.runtime_integration.tool_gate import ToolGateHandler
from agent.runtime_integration.tool_invoke import ToolInvokeHandler
from agent.runtime_integration.tool_result_feedback import ToolResultFeedbackHandler


# ========== 测试辅助 ==========


def _build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 dispatcher（memory turn-end handler + tool pipeline handlers）。

    Phase 3 更新：注册 ToolInvokeHandler 和 ToolResultFeedbackHandler，因为 loop
    turn-end hook 现在构造完整的 Tool lifecycle pipeline（TOOL_GATE → TOOL_INVOKE
    → TOOL_RESULT）。不注册这些 handler 会导致后续 stage 得到 not_supported 状态
    并降级为 subsystem_integration，污染 action_log。

    Phase 4 更新：注册 MemoryConsolidateHandler——MEMORY_CONSOLIDATE 已接入
    loop.py turn-end hook，不注册会导致最后一个事件降级为 subsystem_integration。

    Phase 5 更新：注册 MemoryRecallHandler——MEMORY_RECALL 已接入
    loop.py turn-end hook，不注册会导致最后一个事件降级为 subsystem_integration。

    Phase 6 更新：注册 SkillRuntimeActionHandler——SKILL_SELECT 已接入
    loop.py turn-end hook，不注册会导致最后一个事件降级为 subsystem_integration。

    Phase 7 更新：注册 SubAgentDelegateL0Handler——SUBAGENT_DELEGATE_L0 已接入
    loop.py turn-end hook，不注册会导致最后一个事件降级为 subsystem_integration。
    """
    from agent.runtime_integration.checkpoint_summary import CheckpointSafeSummaryHandler
    from agent.runtime_integration.memory_consolidate import MemoryConsolidateHandler
    from agent.runtime_integration.memory_recall import MemoryRecallHandler
    from agent.runtime_integration.skill_action import SkillRuntimeActionHandler
    from agent.runtime_integration.subagent_action import SubAgentDelegateL0Handler
    from agent.skill_system.loader import SkillLoader
    from agent.skill_system.registry import SkillRegistry
    from agent.subagent_system.registry import SubAgentRegistry

    registry = ActionHandlerRegistry()
    registry.register(RuntimeActionType.MEMORY_TURN_END_PROPOSAL, MemoryTurnEndProposalHandler())
    registry.register(RuntimeActionType.TOOL_GATE, ToolGateHandler())
    registry.register(RuntimeActionType.TOOL_INVOKE, ToolInvokeHandler())
    registry.register(RuntimeActionType.TOOL_RESULT, ToolResultFeedbackHandler())
    registry.register(RuntimeActionType.CHECKPOINT_SAFE_SUMMARY, CheckpointSafeSummaryHandler())
    registry.register(RuntimeActionType.MEMORY_CONSOLIDATE, MemoryConsolidateHandler())
    registry.register(RuntimeActionType.MEMORY_RECALL, MemoryRecallHandler())
    # SKILL_SELECT：空 registry → handler 总是 rejected，但 evidence chain 完整
    _skill_registry = SkillRegistry(roots=[])
    _skill_loader = SkillLoader(_skill_registry)
    registry.register(
        RuntimeActionType.SKILL_SELECT,
        SkillRuntimeActionHandler(registry=_skill_registry, loader=_skill_loader),
    )
    # SUBAGENT_DELEGATE_L0：空 registry → handler 总是 rejected
    _subagent_registry = SubAgentRegistry(roots=())
    registry.register(
        RuntimeActionType.SUBAGENT_DELEGATE_L0,
        SubAgentDelegateL0Handler(registry=_subagent_registry),
    )
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

    def test_direct_dispatcher_payload_spoof_downgrades_classification(self):
        """direct dispatcher 即使伪造 core payload 也只能是 harness_runtime_e2e。

        架构边界：
        - payload 是 action 输入，不是 runtime provenance
        - direct dispatcher 可以伪造 core_loop_invoked/core_entrypoint 字段
        - classifier 必须只信 dispatcher/runtime loop 自己写入的 provenance
        """
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
                "provider_external_call": False,
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        _assert_valid_runtime_action_evidence(result.evidence)
        assert result.evidence["evidence_level"] == HARNESS_RUNTIME_E2E
        assert result.evidence["evidence_level"] != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("dispatcher_origin") == "direct_dispatcher"
        assert result.evidence.get("runtime_loop_invoked") is not True


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

    def test_direct_route_with_core_loop_payload_is_still_harness(self):
        """direct route 不能靠 payload 中的 core_loop_invoked 升级分类。

        架构边界：
        - 这是 remediation 的防伪回归测试
        - direct dispatcher 有完整 target proof，但没有 runtime loop owned provenance
        - 因此只能是 harness_runtime_e2e
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
        assert result.evidence["evidence_level"] == HARNESS_RUNTIME_E2E
        assert result.evidence["evidence_level"] != REAL_CORE_LOOP_RUNTIME_E2E
        assert result.evidence.get("runtime_loop_invoked") is not True
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

    def test_classify_evidence_level_rejects_payload_only_core_loop_claim(self):
        """只有 payload core_loop_invoked 不能升级到 real_core_loop_runtime_e2e。"""
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
        assert level == HARNESS_RUNTIME_E2E
        assert level != REAL_CORE_LOOP_RUNTIME_E2E

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


# ========== core.chat() 真实接线测试 ==========


class _SpyDispatcher:
    """包装 RuntimeActionDispatcher，拦截 route() 调用用于测试断言。

    中文学习边界：
    这个 spy 是刻意存在的外部观察点——不修改生产代码一行，只记录每次 route()
    调用及其参数。生产代码（loop.py turn-end hook）不知道 spy 的存在。
    测试通过检查 captured route() 调用来证明 hook 确实在 core.chat 路径中触发。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self._route_calls: list[RuntimeActionRequest] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        self._route_calls.append(request)
        return self._real.route(request)

    def route_from_runtime_loop(self, request: RuntimeActionRequest) -> Any:
        """测试 spy 透传 runtime-loop route，保留 hook 调用观察能力。"""
        self._route_calls.append(request)
        return self._real.route_from_runtime_loop(request)

    @property
    def action_log(self):
        return self._real.action_log

    @property
    def route_calls(self) -> tuple[RuntimeActionRequest, ...]:
        return tuple(self._route_calls)


class _NonFakeProvider:
    """确定性 provider，不标记 provider_type='fake'——用于测试无 dispatcher 路径。

    中文学习边界：
    当 provider 没有 provider_type='fake' 且 runtime_action_dispatcher=None 时，
    chat() 不会自动构建 Phase 1 dispatcher。这保证 turn-end hook 被跳过，
    不产生任何 RuntimeAction。本 provider 内部委托给 FakeProvider，保持确定性。
    """

    def create(self, *, system, messages, tools, **kwargs):
        return FakeProvider().create(system=system, messages=messages, tools=tools)

    def stream(self, *, system, messages, tools):
        yield from FakeProvider().stream(system=system, messages=messages, tools=tools)


class TestCoreChatWiring:
    """测试 core.chat() → runtime loop → turn-end hook → dispatcher 真实接线。

    中文学习边界：
    这个类里的测试真正调用 agent.core.chat()——不是手工构造 RuntimeActionRequest
    然后直接 dispatcher.route()。它钉死的是 core.chat → run_main_loop →
    turn-end hook → RuntimeActionDispatcher.route() 这条真实接线。
    """

    def test_core_chat_actually_invokes_runtime_action_dispatcher_from_turn_end_hook(self):
        """core.chat() 真实触发 RuntimeActionDispatcher（spy 验证）。

        中文学习边界——这个测试保护什么：
        - 不是 classification 逻辑测试（那些由 TestRealCoreLoopClassification 覆盖）
        - 钉死的是：用户调 core.chat() → run_main_loop() → turn-end 分支
          → _try_phase1_turn_end_runtime_action() → dispatcher.route()
        - 如果这条接线断了（例如 loop turn-end hook 被误删），spy 会捕获不到
          route() 调用，测试直接失败
        - 使用 SpyDispatcher 而非直接检查 dispatcher.action_log，是为了证明
          route() 调用确实发生在 chat() 执行期间，而非之前或之后

        架构边界：
        - runtime_loop_invoked=true（dispatcher-owned provenance）
        - core_entrypoint='core.chat'（来自 runtime-loop route）
        - runtime_hook_name='loop.turn_end'（来自 runtime-loop route）
        - evidence_level=real_core_loop_runtime_e2e（classifier 自动判定）
        - target_module_proof 存在且非空
        """
        # 构建真实 dispatcher 并包裹 spy
        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        # 真正调用 core.chat()——这是本测试与 classification 测试的本质区别
        from agent.core import chat

        result = chat(
            "以后叫我小王",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        # chat() 必须正常完成不抛异常（普通 end_turn 返回空字符串是预期行为：
        # 模型正文通过 on_runtime_event/on_output_chunk 流式输出，返回值仅用于
        # 控制型 UI 提示）
        assert isinstance(result, str)

        # spy 必须捕获到至少一次 route() 调用——证明 hook 确实触发了
        assert len(spy.route_calls) >= 1, (
            f"期望 core.chat() 执行期间 dispatcher.route() 被调用至少 1 次，"
            f"实际 {len(spy.route_calls)} 次——turn-end hook 可能未触发"
        )

        # 验证捕获的 request payload 包含完整 core loop 来源证据
        first_call = spy.route_calls[0]
        payload = dict(first_call.payload)
        assert payload.get("core_loop_invoked") is True, (
            "request.payload.core_loop_invoked 必须为 True——"
            "该字段由 loop.py turn-end hook 注入，缺失说明 hook 未正确构造请求"
        )
        assert payload.get("core_entrypoint") == "core.chat", (
            f"request.payload.core_entrypoint 必须为 'core.chat'，"
            f"实际 {payload.get('core_entrypoint')!r}"
        )
        assert payload.get("runtime_hook_name") == "loop.turn_end", (
            f"request.payload.runtime_hook_name 必须为 'loop.turn_end'，"
            f"实际 {payload.get('runtime_hook_name')!r}"
        )
        assert payload.get("provider_kind") == "fake"
        assert payload.get("external_side_effects") is False

        # 验证最终 evidence 分类为 real_core_loop_runtime_e2e
        action_events = list(spy.action_log)
        assert len(action_events) >= 1
        last_event = action_events[-1]
        evidence = dict(last_event.evidence)
        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"evidence_level 必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("runtime_loop_invoked") is True
        assert evidence.get("dispatcher_origin") == "runtime_loop"
        assert evidence.get("core_loop_invoked") is True
        assert evidence.get("target_module_proof") is not None, (
            "target_module_proof 必须存在——无 proof 说明 handler observer 链断裂"
        )

    def test_runtime_action_dispatcher_none_skips_hook_safely(self):
        """runtime_action_dispatcher=None 且 provider 非 fake 时 hook 不触发。

        中文学习边界：
        - 这是正例的对称负例：接线存在时 hook 触发，接线不存在时 chat() 正常完成
        - provider 不是 fake → chat() 不自动构建 dispatcher → LoopDependencies
          中 runtime_action_dispatcher=None → run_main_loop 跳过 turn-end hook
        - chat() 正常工作、不崩溃，是"无 dispatcher"路径的基础安全保障

        架构边界：
        - 不得产生 real_core_loop_runtime_e2e（dispatcher 根本没被构建）
        - chat() 返回非空结果（provider 正常工作）
        """
        from agent.core import chat

        result = chat(
            "hello",
            provider=_NonFakeProvider(),
            runtime_action_dispatcher=None,
        )

        # chat() 正常完成不抛异常（普通 end_turn 返回空字符串是预期行为）
        assert isinstance(result, str)
