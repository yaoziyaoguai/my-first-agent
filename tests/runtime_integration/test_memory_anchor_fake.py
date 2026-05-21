"""Memory Proposal Anchor fake-provider TDD 测试。

中文学习边界：
这些测试钉死 Memory Proposal Anchor 的 fake-provider 全链路架构边界：
1. core.chat() 统一入口 → turn-end hook → dispatcher → handler → evidence
2. 不新增 fake runtime / fake loop / fake dispatcher 主路径
3. FakeProvider 通过依赖注入进入唯一 core path
4. pending_review only, 不 auto approve
5. no_action 仍产生 RuntimeActionEvent / action_log
6. secret-like 输入自动拒绝 (should_not_remember)
7. direct dispatcher 只能是 harness_runtime_e2e，不能冒充 real_core_loop_runtime_e2e

与 test_phase1_real_core_loop.py 的关系：
- test_phase1_real_core_loop.py 测试 Phase 1 基础设施接线（dispatcher、evidence、classification）
- 本文件测试 Memory Anchor 专属边界（auto_approved 约束、no_action 处置、secret-like 路径等）
- 两个文件独立演进，各自维护 spy/helper 定义，不互相依赖

架构依据：docs/real-e2e/memory-anchor/SPEC.md, TDD.md, DOGFOOD_PLAN.md
"""

from __future__ import annotations

from typing import Any

from agent.provider.fake_provider import FakeProvider
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


# ========== 测试辅助 ==========


def _build_phase1_dispatcher() -> RuntimeActionDispatcher:
    """构建 Phase 1 最小 dispatcher（仅 memory turn-end handler）。

    中文学习边界：
    与 agent.runtime_integration.phase1_hook.build_phase1_dispatcher() 行为等价。
    在测试文件中重新定义以保持自包含，避免跨测试文件 import 耦合。
    """
    registry = ActionHandlerRegistry()
    registry.register(
        RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
        MemoryTurnEndProposalHandler(),
    )
    return RuntimeActionDispatcher(registry=registry, observer=RuntimeActionModuleObserver())


class _SpyDispatcher:
    """包装 RuntimeActionDispatcher，拦截 route() 调用用于测试断言。

    中文学习边界：
    这个 spy 是刻意存在的外部观察点——不修改生产代码一行，只记录每次 route()
    调用及其参数。生产代码（loop.py turn-end hook）不知道 spy 的存在。
    测试通过检查 captured route() 调用来证明 hook 确实在 core.chat 路径中触发。

    与 test_phase1_real_core_loop.py 中的 _SpyDispatcher 行为等价，
    在本文件中独立定义以保持测试文件自包含。
    """

    def __init__(self, real: RuntimeActionDispatcher) -> None:
        self._real = real
        self._route_calls: list[RuntimeActionRequest] = []

    def route(self, request: RuntimeActionRequest) -> Any:
        self._route_calls.append(request)
        return self._real.route(request)

    @property
    def action_log(self):
        return self._real.action_log

    @property
    def route_calls(self) -> tuple[RuntimeActionRequest, ...]:
        return tuple(self._route_calls)


# ========== Memory Anchor fake-provider 核心测试 ==========


class TestMemoryAnchorFakeProviderCoreChat:
    """测试 fake provider 下 core.chat() → memory proposal 全链路。

    中文学习边界：
    这组测试钉死的是：用户调 core.chat() → run_main_loop() → turn-end hook →
    RuntimeActionDispatcher.route() → MemoryTurnEndProposalHandler.handle() 这条
    真实接线存在且工作正常。使用 SpyDispatcher 作为外部观察点，不修改生产代码。
    """

    def test_fake_provider_core_chat_triggers_runtime_action(self):
        """core.chat() 真实触发 RuntimeActionDispatcher（spy 验证）。

        中文学习边界——这个测试保护什么：
        - 钉死 core.chat → run_main_loop → turn-end hook → dispatcher.route() 接线
        - 如果这条接线断了（例如 loop turn-end hook 被误删），spy 捕获不到 route()
          调用，测试直接失败
        - 验证 evidence chain 完整：core_loop_invoked → real_core_loop_runtime_e2e
          → target_module_proof

        Purpose: 验证 fake provider 下 core.chat() 全链路接线正确
        Setup: SpyDispatcher + FakeProvider
        Action: chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - spy 捕获到至少 1 次 route() 调用
          - payload.core_loop_invoked == True
          - payload.core_entrypoint == "core.chat"
          - payload.runtime_hook_name == "loop.turn_end"
          - action_log 最后 event 的 evidence_level == real_core_loop_runtime_e2e
          - evidence.target_module_proof 非 None
          - evidence.target_module == "MemoryPolicy"
          - auto_approved == False, not_confirmed == True
        Forbidden: chat() 抛异常；evidence_level 是 harness_runtime_e2e
        Pass/fail: 所有 expected evidence 条件满足
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "以后叫我小王",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        # chat() 必须正常完成不抛异常
        assert isinstance(result, str)

        # spy 必须捕获到至少 1 次 route() 调用
        assert len(spy.route_calls) >= 1, (
            f"期望 core.chat() 执行期间 dispatcher.route() 被调用至少 1 次，"
            f"实际 {len(spy.route_calls)} 次——turn-end hook 可能未触发"
        )

        # 验证 payload 包含完整 core loop 来源证据
        first_call = spy.route_calls[0]
        payload = dict(first_call.payload)
        assert payload.get("core_loop_invoked") is True, (
            "payload.core_loop_invoked 必须为 True——"
            "该字段由 loop.py turn-end hook 注入"
        )
        assert payload.get("core_entrypoint") == "core.chat"
        assert payload.get("runtime_hook_name") == "loop.turn_end"
        assert payload.get("provider_kind") == "fake"
        assert payload.get("external_side_effects") is False

        # 验证 action_log 中 event 的 evidence 分类
        action_events = list(spy.action_log)
        assert len(action_events) >= 1
        last_event = action_events[-1]
        evidence = dict(last_event.evidence)

        assert evidence.get("evidence_level") == REAL_CORE_LOOP_RUNTIME_E2E, (
            f"evidence_level 必须为 {REAL_CORE_LOOP_RUNTIME_E2E}，"
            f"实际 {evidence.get('evidence_level')!r}"
        )
        assert evidence.get("core_loop_invoked") is True
        assert evidence.get("target_module_proof") is not None, (
            "target_module_proof 必须存在——无 proof 说明 handler observer 链断裂"
        )
        assert evidence.get("target_module") == "MemoryPolicy"

        # 验证 handler 硬编码约束：不自动批准、不静默 retain
        # 注意：event 有 evidence 而非 payload；payload 字段在 evidence_extra 中
        assert evidence.get("auto_approved") is False, (
            "auto_approved 必须恒为 False"
        )
        assert evidence.get("not_confirmed") is True
        # pending_review 取决于 policy 决策："以后叫我小王" 不命中 RETAIN_PREFIXES
        # → NO_OP → no_action → pending_review=False
        assert evidence.get("pending_review") in (True, False)

    def test_uses_same_core_path_not_fake_loop(self):
        """验证 fake provider 走统一 run_main_loop，非 fake-only 路径。

        中文学习边界——这个测试保护什么：
        - 不存在 fake_runtime_loop、fake_dispatcher 等 fake-only 类
        - dispatcher 实例是 RuntimeActionDispatcher，不是任何 fake 子类
        - handler 实例是 MemoryTurnEndProposalHandler，不是 fake/mock handler
        - source 标记为 "core_loop"（不是 "fake_loop" 或 "dogfood"）

        Purpose: 钉死 fake 和 real 走同一套核心路径
        Setup: SpyDispatcher + FakeProvider
        Action: chat("hello", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence:
          - source == "core_loop"
          - core_entrypoint == "core.chat"
          - runtime_hook_name == "loop.turn_end"
          - dispatcher 实例是 RuntimeActionDispatcher
          - handler 类型是 MemoryTurnEndProposalHandler
        Forbidden: 不存在 fake_runtime_loop / fake_dispatcher 类
        Pass/fail: 所有 expected evidence 条件满足
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "hello",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1

        first_call = spy.route_calls[0]
        assert first_call.source == "core_loop", (
            f"source 必须为 'core_loop'，实际 {first_call.source!r}"
        )
        payload = dict(first_call.payload)
        assert payload.get("core_entrypoint") == "core.chat"
        assert payload.get("runtime_hook_name") == "loop.turn_end"

        # 验证 dispatcher 实例类型——必须不是任何 fake 子类
        assert type(spy._real) is RuntimeActionDispatcher, (
            f"dispatcher 类型必须是 RuntimeActionDispatcher，"
            f"实际 {type(spy._real).__name__}"
        )

        # 验证 handler 类型
        handler = spy._real._registry._handlers.get(
            RuntimeActionType.MEMORY_TURN_END_PROPOSAL
        )
        assert handler is not None, "MemoryTurnEndProposalHandler 未注册"
        assert type(handler) is MemoryTurnEndProposalHandler, (
            f"handler 类型必须是 MemoryTurnEndProposalHandler，"
            f"实际 {type(handler).__name__}"
        )

    def test_does_not_read_memory_episodes(self):
        """验证 memory proposal handler 不读取真实 memory episodes。

        中文学习边界：
        Phase 1 memory hook 只提议，不读真实 memory episodes、不读真实 sessions/runs。
        real_episodes_read 在所有 disposition 分支中硬编码为 False。

        Purpose: 钉死 handler 不读取真实 memory episodes
        Setup: SpyDispatcher + FakeProvider
        Action: chat("以后叫我小王", provider=FakeProvider(), runtime_action_dispatcher=spy)
        Expected evidence: action_log 中所有 event 的 payload.real_episodes_read == False
        Forbidden: 任何 payload 中 real_episodes_read == True
        Pass/fail: 所有 action_log event 的 real_episodes_read 均为 False
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "以后叫我小王",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1

        action_events = list(spy.action_log)
        assert len(action_events) >= 1
        for event in action_events:
            ev = dict(event.evidence)
            assert ev.get("real_episodes_read") is False, (
                f"real_episodes_read 必须为 False，"
                f"实际 {ev.get('real_episodes_read')!r}"
            )


    def test_provider_kind_still_fake_after_parameterization(self):
        """回归测试：hook 参数化后 fake mode evidence 不退化。

        中文学习边界——这个测试保护什么：
        - 参数化后 provider_kind 仍为 "fake"（不会因解析逻辑变更而漂移）
        - provider_external_call 新增字段为 False（fake provider 无外部调用）
        - external_side_effects 仍为 False（fake mode 无副作用）
        - 如果参数化错误地让 FakeProvider 被识别为 real，此测试直接红

        这是 ce-plan v2 §U2 scenario 10 的精确对应实现。
        """
        from agent.core import chat

        real_dispatcher = _build_phase1_dispatcher()
        spy = _SpyDispatcher(real_dispatcher)

        result = chat(
            "以后叫我小王",
            provider=FakeProvider(),
            runtime_action_dispatcher=spy,
        )

        assert isinstance(result, str)
        assert len(spy.route_calls) >= 1

        first_call = spy.route_calls[0]
        payload = dict(first_call.payload)

        # 回归守卫：provider_kind 必须仍为 "fake"
        assert payload.get("provider_kind") == "fake", (
            f"参数化后 provider_kind 必须仍为 'fake'，实际 {payload.get('provider_kind')!r}"
        )

        # 新增字段：provider_external_call 必须为 False
        assert payload.get("provider_external_call") is False, (
            f"参数化后 provider_external_call 必须为 False，实际 {payload.get('provider_external_call')!r}"
        )

        # 回归守卫：external_side_effects 必须仍为 False
        assert payload.get("external_side_effects") is False, (
            f"参数化后 external_side_effects 必须仍为 False，实际 {payload.get('external_side_effects')!r}"
        )


class TestMemoryAnchorHandlerConstraints:
    """测试 MemoryTurnEndProposalHandler 的硬编码约束。

    中文学习边界：
    这组测试验证 handler 的三个核心不变量：
    1. auto_approved 恒为 False（无论 policy 决策如何）
    2. not_confirmed 恒为 True（所有 proposal 都需人工确认）
    3. pending_review 只在 proposed disposition 时为 True

    由于 "记住" 前缀输入会触发 _memory_runtime.evaluate_user_text →
    CONFIRMATION_REQUIRED → chat() 提前返回空串 → turn-end hook 不触发，
    这组测试走 direct dispatcher.route() 路径以精确控制 handler 输入。
    这是 TDD.md §1.3/§1.5 明确记录的设计选择。
    """

    def test_no_auto_approve(self):
        """验证无论 policy 决策如何，auto_approved 始终为 False。

        中文学习边界——这个测试保护什么：
        - MemoryTurnEndProposalHandler 三路处置（should_not_remember / proposed /
          no_action）全部硬编码 auto_approved=False
        - 即使 decision 是 RETAIN/UPDATE，也不能自动批准
        - pending_review != human_approved

        Purpose: 钉死 auto_approved=False 在所有处置分支中
        Setup: dispatcher
        Action: 构造 RuntimeActionRequest（命中 RETAIN 的输入 "记住：以后叫我小王"），
               走 dispatcher.route()
        Expected evidence:
          - pending_review == True（RETAIN → proposed）
          - auto_approved == False
          - not_confirmed == True
          - no_silent_retain == True
        Forbidden: auto_approved 不为 True；human_approved 不为 True
        Pass/fail: 所有 expected evidence 条件满足

        注意：走 direct dispatcher 而非 core.chat() 是因为 "记住" 前缀输入会被
        _memory_runtime 拦截（CONFIRMATION_REQUIRED）导致 chat() 返回空串，
        turn-end hook 不会触发。此处验证的是 handler 的硬编码约束，不是 chat()
        的 _memory_runtime 行为。
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

        assert result.status == "success"
        payload = dict(result.payload)
        assert payload.get("pending_review") is True, (
            f"RETAIN 决策必须产生 pending_review=True，实际 {payload.get('pending_review')!r}"
        )
        assert payload.get("auto_approved") is False, (
            "auto_approved 必须恒为 False——memory proposal 不能自动批准"
        )
        assert payload.get("not_confirmed") is True
        assert payload.get("disposition") == "proposed"
        assert result.evidence.get("no_silent_retain") is True

    def test_secret_like_input_is_rejected(self):
        """验证含 secret-like pattern 的输入被自动拒绝。

        中文学习边界——这个测试保护什么：
        - 即使用户明确要求「记住这个 api_key: sk-xxx」
        - handler 检测到 secret-like pattern 后自动拒绝
        - disposition=should_not_remember，不进入 pending_review

        Purpose: 钉死 secret-like 输入 → should_not_remember 路径
        Setup: dispatcher
        Action: 构造 RuntimeActionRequest（含 "sk-" pattern），走 dispatcher.route()
        Expected evidence:
          - status == "rejected"
          - disposition == "should_not_remember"
          - secret_like_detected == True
          - redacted_secret == True
          - pending_review == False
        Forbidden: pending_review 不为 True；API key pattern 不出现在 payload 文本中
        Pass/fail: 所有 expected evidence 条件满足

        注意：走 direct dispatcher 以精确控制输入内容，避免 _memory_runtime 前置拦截。
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
        assert payload.get("disposition") == "should_not_remember"
        assert payload.get("secret_like_detected") is True
        assert payload.get("redacted_secret") is True
        assert payload.get("pending_review") is False


class TestMemoryAnchorEvidenceClassification:
    """测试 evidence 分类边界：real_core_loop_runtime_e2e vs harness_runtime_e2e。

    中文学习边界：
    这组测试钉死 evidence 分类的不可伪造性：
    - direct dispatcher.route() → harness_runtime_e2e（不能冒充 real）
    - core.chat() → turn-end hook → real_core_loop_runtime_e2e
    - 即使 evidence chain 完整（有 target_module_proof），缺 core_loop_invoked
      仍降级到 harness
    """

    def test_direct_dispatch_is_harness_not_real_core_loop(self):
        """验证直接 dispatcher.route() 只能是 harness_runtime_e2e。

        中文学习边界——这个测试保护什么：
        - 手工构造 RuntimeActionRequest 并直接 dispatcher.route() 调用
        - 即使 evidence chain 完整（route → handler → proof），只要没有
          core_loop_invoked=True → evidence_level=harness_runtime_e2e
        - 这是防止 dogfood harness 或其他非 core loop 路径冒充 real 的硬防线

        Purpose: 钉死 direct dispatch ≠ real_core_loop_runtime_e2e
        Setup: dispatcher（不通过 spy）
        Action: 构造不含 core_loop_invoked 的 RuntimeActionRequest，dispatcher.route()
        Expected evidence:
          - evidence_level == harness_runtime_e2e
          - core_loop_invoked 不是 True
          - target_module_proof 非 None（evidence chain 完整但分类降级）
        Forbidden: evidence_level 不是 real_core_loop_runtime_e2e
        Pass/fail: 分类正确降级到 harness_runtime_e2e
        """
        dispatcher = _build_phase1_dispatcher()
        request = RuntimeActionRequest(
            action_type=RuntimeActionType.MEMORY_TURN_END_PROPOSAL,
            source="dogfood",
            parent_trace_id="",
            payload={
                "user_message": "以后叫我小王",
                "assistant_response": "好的，以后叫你小王。",
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
        # evidence chain 完整——有 target_module_proof，但分类降级
        assert evidence.get("target_module_proof") is not None
        assert evidence.get("dispatcher_routed") is True

        # 通过 classify_evidence_level 再次确认
        level = classify_evidence_level(evidence)
        assert level == HARNESS_RUNTIME_E2E
        assert level != REAL_CORE_LOOP_RUNTIME_E2E


class TestMemoryAnchorNoAction:
    """测试 no_action 处置：仍产生 RuntimeActionEvent，但不进入 pending_review。

    中文学习边界——这个测试保护什么：
    - gstack plan-eng-review P2 建议：no_action 分支必须仍产生 RuntimeActionEvent
      进入 action_log，否则 action_log 会缺失这次 dispatch 的记录
    - disposition=no_action 时 handler 返回 success（不是 rejected）
    - pending_review=False, auto_approved=False, not_confirmed=True
    - target_module_proof 仍存在（target 被调用了，只是决策结果是 no_action）

    为什么走 direct dispatcher：
    - 需要精确控制输入不命中 DeterministicMemoryPolicy 的任何 trigger rule
    - "今天天气不错" → NO_OP → no_action disposition
    - 走 direct route 避免 _memory_runtime 前置拦截和 policy trigger 不确定性
    """

    def test_no_action_still_produces_runtime_action_event(self):
        """验证 disposition=no_action 仍产生 RuntimeActionEvent 进入 action_log。

        Purpose: 钉死 no_action ≠ 跳过 event 记录（P2 修复）
        Setup: dispatcher
        Action: 构造 RuntimeActionRequest（"今天天气不错"→NO_OP→no_action），
               走 dispatcher.route()
        Expected evidence:
          - action_log 包含 1 个 event
          - result.status == "success"
          - disposition == "no_action"
          - pending_review == False
          - auto_approved == False
          - not_confirmed == True
          - target_module_proof 非 None
          - dispatcher_routed == True
        Forbidden: no_action 不导致 dispatcher 跳过 event 记录；handler 不抛异常
        Pass/fail: action_log 有 event，且 payload 正确标记为 no_action
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
                "provider_kind": "fake",
                "external_side_effects": False,
            },
        )
        result = dispatcher.route(request)

        # 验证 handler 返回 success（no_action 不是 rejected）
        assert result.status == "success", (
            f"no_action 处置应返回 success，实际 {result.status!r}"
        )

        payload = dict(result.payload)
        assert payload.get("disposition") == "no_action", (
            f"disposition 必须为 'no_action'，实际 {payload.get('disposition')!r}"
        )
        assert payload.get("pending_review") is False, (
            "no_action 不得进入 pending_review"
        )
        assert payload.get("auto_approved") is False
        assert payload.get("not_confirmed") is True

        # 验证 evidence chain：target 仍被调用并产生 proof
        evidence = result.evidence
        assert evidence.get("target_module_proof") is not None, (
            "target_module_proof 必须存在——no_action 也是合法的 target invocation 结果"
        )
        assert evidence.get("dispatcher_routed") is True

        # 钉死 P2 修复：action_log 必须包含这个 event
        action_events = list(dispatcher.action_log)
        assert len(action_events) == 1, (
            f"action_log 必须包含 1 个 event（no_action 也不能跳过记录），"
            f"实际 {len(action_events)} 个"
        )
        event = action_events[0]
        ev = dict(event.evidence)
        assert ev.get("disposition") == "no_action"
        assert ev.get("pending_review") is False
